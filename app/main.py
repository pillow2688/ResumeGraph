from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import cast

from fastapi import FastAPI

from app.api.routes.admin_access_grants import router as admin_access_grants_router
from app.api.routes.admin_auth import router as admin_auth_router
from app.api.routes.admin_documents import router as admin_documents_router
from app.api.routes.admin_ingestion import router as admin_ingestion_router
from app.api.routes.admin_projects import router as admin_projects_router
from app.api.routes.admin_public_demo import router as admin_public_demo_router
from app.api.routes.admin_publication import router as admin_publication_router
from app.api.routes.admin_users import router as admin_users_router
from app.api.routes.health import router as health_router
from app.api.routes.interview import router as interview_router
from app.api.routes.public_demo import router as public_demo_router
from app.api.routes.recruiter_access import router as recruiter_access_router
from app.core.config import Settings
from app.core.exceptions import install_exception_handlers
from app.core.logging import configure_logging
from app.infrastructure.admin_login_limiter import AdminLoginRateLimiter
from app.infrastructure.admin_session import AdminSessionStore
from app.infrastructure.chat import (
    ChatProvider,
    OpenAICompatibleChatProvider,
    UnconfiguredChatProvider,
)
from app.infrastructure.database import Database
from app.infrastructure.embedding import (
    EmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    UnconfiguredEmbeddingProvider,
)
from app.infrastructure.failure_limiter import FailureRateLimiter
from app.infrastructure.health import HealthDependency
from app.infrastructure.interview_conversation import InterviewConversationStore
from app.infrastructure.job_queue import ArqJobQueue
from app.infrastructure.recruiter_session import RecruiterSessionStore
from app.infrastructure.redis import RedisConnection, RedisOperations
from app.quality.rules import RuleConfig
from app.repositories.access_grant import AccessGrantRepository
from app.repositories.admin_user import AdminUserRepository, DatabaseSessionProvider
from app.repositories.deduplication import DeduplicationRepository
from app.repositories.indexing import IndexingRepository
from app.repositories.ingestion import IngestionRepository
from app.repositories.knowledge_document import KnowledgeDocumentRepository
from app.repositories.knowledge_lifecycle import KnowledgeLifecycleRepository
from app.repositories.project import ProjectRepository
from app.repositories.public_demo import PublicDemoRepository
from app.repositories.publication import PublicationRepository
from app.repositories.retrieval import RetrievalRepository
from app.services.access_grant import AccessGrantService
from app.services.admin_auth import AdminAuthService
from app.services.admin_user_management import AdminUserManagementService
from app.services.deduplication import DeduplicationService
from app.services.indexing import IndexingService
from app.services.ingestion import IngestionService
from app.services.interview import InterviewService
from app.services.interview_workflow import InterviewWorkflowService
from app.services.knowledge_document import KnowledgeDocumentService
from app.services.knowledge_lifecycle import KnowledgeLifecycleService
from app.services.project import ProjectService
from app.services.public_demo import PublicDemoService
from app.services.publication import PublicationService
from app.services.retrieval import RetrievalService


def create_app(
    *,
    settings: Settings | None = None,
    database: HealthDependency | None = None,
    redis: HealthDependency | None = None,
    admin_auth_service: AdminAuthService | None = None,
    admin_user_service: AdminUserManagementService | None = None,
    access_grant_service: AccessGrantService | None = None,
    project_service: ProjectService | None = None,
    knowledge_document_service: KnowledgeDocumentService | None = None,
    ingestion_service: IngestionService | None = None,
    indexing_service: IndexingService | None = None,
    publication_service: PublicationService | None = None,
    deduplication_service: DeduplicationService | None = None,
    knowledge_lifecycle_service: KnowledgeLifecycleService | None = None,
    interview_service: InterviewService | None = None,
    interview_workflow_service: InterviewWorkflowService | None = None,
    public_demo_service: PublicDemoService | None = None,
) -> FastAPI:
    """Build an application whose shared infrastructure is owned by its lifespan."""
    application_settings = settings or Settings()
    configure_logging(application_settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database_connection = database or Database(
            application_settings.database_url.get_secret_value(),
            timeout_seconds=application_settings.dependency_timeout_seconds,
        )
        redis_connection = redis or RedisConnection(
            application_settings.redis_url.get_secret_value(),
            timeout_seconds=application_settings.dependency_timeout_seconds,
        )
        authentication_service = admin_auth_service
        admin_repository = AdminUserRepository(cast(DatabaseSessionProvider, database_connection))
        if authentication_service is None:
            redis_operations = cast(RedisOperations, redis_connection)
            authentication_service = AdminAuthService(
                admin_repository,
                AdminSessionStore(redis_operations),
                AdminLoginRateLimiter(
                    redis_operations,
                    max_failures=application_settings.admin_login_max_failures,
                    window_seconds=application_settings.admin_login_window_seconds,
                ),
                session_ttl_seconds=application_settings.admin_session_ttl_seconds,
                login_max_failures=application_settings.admin_login_max_failures,
                dependency_timeout_seconds=application_settings.dependency_timeout_seconds,
            )
        administrator_management_service = admin_user_service
        if administrator_management_service is None:
            administrator_management_service = AdminUserManagementService(
                admin_repository,
                dependency_timeout_seconds=application_settings.dependency_timeout_seconds,
            )
        recruiter_access_service = access_grant_service
        if recruiter_access_service is None:
            access_repository = AccessGrantRepository(
                cast(DatabaseSessionProvider, database_connection)
            )
            redis_operations = cast(RedisOperations, redis_connection)
            recruiter_access_service = AccessGrantService(
                access_repository,
                RecruiterSessionStore(redis_operations),
                FailureRateLimiter(
                    redis_operations,
                    key_prefix="access_exchange_failures",
                    max_failures=application_settings.access_exchange_failure_limit,
                    window_seconds=application_settings.access_exchange_failure_window_seconds,
                ),
                access_token_pepper=application_settings.access_token_pepper.get_secret_value(),
                recruiter_session_ttl_seconds=(application_settings.recruiter_session_ttl_seconds),
                access_exchange_failure_limit=(application_settings.access_exchange_failure_limit),
                dependency_timeout_seconds=application_settings.dependency_timeout_seconds,
            )
        public_demo_management_service = public_demo_service
        if public_demo_management_service is None:
            public_demo_management_service = PublicDemoService(
                PublicDemoRepository(cast(DatabaseSessionProvider, database_connection)),
                recruiter_access_service,
            )
        project_management_service = project_service
        if project_management_service is None:
            project_management_service = ProjectService(
                ProjectRepository(cast(DatabaseSessionProvider, database_connection)),
                dependency_timeout_seconds=application_settings.dependency_timeout_seconds,
            )
        document_management_service = knowledge_document_service
        if document_management_service is None:
            document_management_service = KnowledgeDocumentService(
                KnowledgeDocumentRepository(cast(DatabaseSessionProvider, database_connection)),
                markdown_max_bytes=application_settings.markdown_max_bytes,
                dependency_timeout_seconds=application_settings.dependency_timeout_seconds,
            )
        document_processing_service = ingestion_service
        knowledge_indexing_service = indexing_service
        job_queue: ArqJobQueue | None = None
        if document_processing_service is None or knowledge_indexing_service is None:
            job_queue = ArqJobQueue(
                application_settings.redis_url.get_secret_value(),
                timeout_seconds=application_settings.dependency_timeout_seconds,
            )
        if document_processing_service is None:
            document_processing_service = IngestionService(
                IngestionRepository(cast(DatabaseSessionProvider, database_connection)),
                cast(ArqJobQueue, job_queue),
                dependency_timeout_seconds=application_settings.dependency_timeout_seconds,
            )
        if knowledge_indexing_service is None:
            knowledge_indexing_service = IndexingService(
                IndexingRepository(cast(DatabaseSessionProvider, database_connection)),
                cast(ArqJobQueue, job_queue),
                dependency_timeout_seconds=application_settings.dependency_timeout_seconds,
            )
        knowledge_deduplication_service = deduplication_service
        embedding_provider: EmbeddingProvider | None = None
        embedding_provider_to_close = None
        if knowledge_deduplication_service is None and (
            publication_service is None or knowledge_lifecycle_service is None
        ):
            if application_settings.embedding_api_key.get_secret_value():
                embedding_provider = OpenAICompatibleEmbeddingProvider(
                    provider_name=application_settings.embedding_provider_name,
                    api_key=application_settings.embedding_api_key,
                    base_url=application_settings.embedding_base_url,
                    model_name=application_settings.embedding_model,
                    dimensions=application_settings.embedding_dimensions,
                    send_dimensions=application_settings.embedding_send_dimensions,
                    batch_size=application_settings.embedding_batch_size,
                    timeout_seconds=application_settings.embedding_timeout_seconds,
                    max_retries=application_settings.embedding_max_retries,
                )
                embedding_provider_to_close = embedding_provider
            else:
                embedding_provider = UnconfiguredEmbeddingProvider(
                    provider_name=application_settings.embedding_provider_name,
                    model_name=application_settings.embedding_model,
                    dimensions=application_settings.embedding_dimensions,
                )
            knowledge_deduplication_service = DeduplicationService(
                DeduplicationRepository(cast(DatabaseSessionProvider, database_connection)),
                embedding_provider,
                dependency_timeout_seconds=application_settings.dependency_timeout_seconds,
                rule_config=RuleConfig(
                    min_characters=application_settings.quality_rule_min_characters,
                    max_characters=application_settings.quality_rule_max_characters,
                    abnormal_character_ratio=(
                        application_settings.quality_rule_abnormal_character_ratio
                    ),
                ),
            )
        knowledge_publication_service = publication_service
        if knowledge_publication_service is None:
            knowledge_publication_service = PublicationService(
                PublicationRepository(cast(DatabaseSessionProvider, database_connection)),
                provider_name=application_settings.embedding_provider_name,
                model_name=application_settings.embedding_model,
                dimensions=application_settings.embedding_dimensions,
                dependency_timeout_seconds=application_settings.dependency_timeout_seconds,
                deduplication_service=knowledge_deduplication_service,
            )
        lifecycle_management_service = knowledge_lifecycle_service
        if lifecycle_management_service is None:
            lifecycle_management_service = KnowledgeLifecycleService(
                KnowledgeLifecycleRepository(cast(DatabaseSessionProvider, database_connection)),
                cast(DeduplicationService, knowledge_deduplication_service),
                dependency_timeout_seconds=application_settings.dependency_timeout_seconds,
            )

        interview_answering_service = interview_service
        multi_agent_interview_service = interview_workflow_service
        chat_provider_to_close: OpenAICompatibleChatProvider | None = None
        runtime_chat_provider: ChatProvider | None = None
        runtime_retrieval_service: RetrievalService | None = None
        runtime_quota_repository: AccessGrantRepository | None = None
        if interview_answering_service is None or multi_agent_interview_service is None:
            if embedding_provider is None:
                if application_settings.embedding_api_key.get_secret_value():
                    embedding_provider = OpenAICompatibleEmbeddingProvider(
                        provider_name=application_settings.embedding_provider_name,
                        api_key=application_settings.embedding_api_key,
                        base_url=application_settings.embedding_base_url,
                        model_name=application_settings.embedding_model,
                        dimensions=application_settings.embedding_dimensions,
                        send_dimensions=application_settings.embedding_send_dimensions,
                        batch_size=application_settings.embedding_batch_size,
                        timeout_seconds=application_settings.embedding_timeout_seconds,
                        max_retries=application_settings.embedding_max_retries,
                    )
                    embedding_provider_to_close = embedding_provider
                else:
                    embedding_provider = UnconfiguredEmbeddingProvider(
                        provider_name=application_settings.embedding_provider_name,
                        model_name=application_settings.embedding_model,
                        dimensions=application_settings.embedding_dimensions,
                    )
            if application_settings.deepseek_api_key.get_secret_value():
                configured_chat_provider = OpenAICompatibleChatProvider(
                    provider_name="deepseek",
                    api_key=application_settings.deepseek_api_key,
                    base_url=application_settings.deepseek_base_url,
                    model_name=application_settings.deepseek_quality_model,
                    timeout_seconds=application_settings.rag_answer_timeout_seconds,
                )
                runtime_chat_provider = configured_chat_provider
                chat_provider_to_close = configured_chat_provider
            else:
                runtime_chat_provider = UnconfiguredChatProvider(
                    provider_name="deepseek",
                    model_name=application_settings.deepseek_quality_model,
                )
            runtime_quota_repository = AccessGrantRepository(
                cast(DatabaseSessionProvider, database_connection)
            )
            runtime_retrieval_service = RetrievalService(
                RetrievalRepository(cast(DatabaseSessionProvider, database_connection)),
                embedding_provider,
                top_k=application_settings.rag_top_k,
                max_context_characters=application_settings.rag_max_context_characters,
                dependency_timeout_seconds=max(
                    application_settings.embedding_timeout_seconds,
                    application_settings.dependency_timeout_seconds,
                ),
            )

        if interview_answering_service is None:
            interview_answering_service = InterviewService(
                cast(AccessGrantRepository, runtime_quota_repository),
                cast(RetrievalService, runtime_retrieval_service),
                cast(ChatProvider, runtime_chat_provider),
                output_retry_count=application_settings.rag_answer_output_retries,
                dependency_timeout_seconds=application_settings.rag_answer_timeout_seconds,
            )
        if multi_agent_interview_service is None:
            multi_agent_interview_service = InterviewWorkflowService(
                cast(AccessGrantRepository, runtime_quota_repository),
                InterviewConversationStore(
                    cast(RedisOperations, redis_connection),
                    max_turns=application_settings.conversation_max_turns,
                ),
                retrieval_service=cast(RetrievalService, runtime_retrieval_service),
                chat_provider=cast(ChatProvider, runtime_chat_provider),
                settings=application_settings,
            )

        async with AsyncExitStack() as stack:
            stack.push_async_callback(database_connection.close)
            stack.push_async_callback(redis_connection.close)
            if job_queue is not None:
                stack.push_async_callback(job_queue.close)
            if embedding_provider_to_close is not None:
                stack.push_async_callback(embedding_provider_to_close.close)
            if chat_provider_to_close is not None:
                stack.push_async_callback(chat_provider_to_close.close)
            application.state.settings = application_settings
            application.state.database = database_connection
            application.state.redis = redis_connection
            application.state.admin_auth_service = authentication_service
            application.state.admin_user_service = administrator_management_service
            application.state.access_grant_service = recruiter_access_service
            application.state.public_demo_service = public_demo_management_service
            application.state.project_service = project_management_service
            application.state.knowledge_document_service = document_management_service
            application.state.ingestion_service = document_processing_service
            application.state.indexing_service = knowledge_indexing_service
            application.state.publication_service = knowledge_publication_service
            application.state.deduplication_service = knowledge_deduplication_service
            application.state.knowledge_lifecycle_service = lifecycle_management_service
            application.state.interview_service = interview_answering_service
            application.state.interview_workflow_service = multi_agent_interview_service
            yield

    application = FastAPI(
        title=application_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    install_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(admin_auth_router)
    application.include_router(admin_users_router)
    application.include_router(admin_access_grants_router)
    application.include_router(admin_public_demo_router)
    application.include_router(admin_documents_router)
    application.include_router(admin_ingestion_router)
    application.include_router(admin_projects_router)
    application.include_router(admin_publication_router)
    application.include_router(recruiter_access_router)
    application.include_router(public_demo_router)
    application.include_router(interview_router)
    return application


app = create_app()
