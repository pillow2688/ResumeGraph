from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import cast

from fastapi import FastAPI

from app.api.routes.admin_access_grants import router as admin_access_grants_router
from app.api.routes.admin_auth import router as admin_auth_router
from app.api.routes.admin_documents import router as admin_documents_router
from app.api.routes.admin_ingestion import router as admin_ingestion_router
from app.api.routes.admin_projects import router as admin_projects_router
from app.api.routes.health import router as health_router
from app.api.routes.recruiter_access import router as recruiter_access_router
from app.core.config import Settings
from app.core.exceptions import install_exception_handlers
from app.core.logging import configure_logging
from app.infrastructure.admin_login_limiter import AdminLoginRateLimiter
from app.infrastructure.admin_session import AdminSessionStore
from app.infrastructure.database import Database
from app.infrastructure.failure_limiter import FailureRateLimiter
from app.infrastructure.health import HealthDependency
from app.infrastructure.job_queue import ArqJobQueue
from app.infrastructure.recruiter_session import RecruiterSessionStore
from app.infrastructure.redis import RedisConnection, RedisOperations
from app.repositories.access_grant import AccessGrantRepository
from app.repositories.admin_user import AdminUserRepository, DatabaseSessionProvider
from app.repositories.ingestion import IngestionRepository
from app.repositories.knowledge_document import KnowledgeDocumentRepository
from app.repositories.project import ProjectRepository
from app.services.access_grant import AccessGrantService
from app.services.admin_auth import AdminAuthService
from app.services.ingestion import IngestionService
from app.services.knowledge_document import KnowledgeDocumentService
from app.services.project import ProjectService


def create_app(
    *,
    settings: Settings | None = None,
    database: HealthDependency | None = None,
    redis: HealthDependency | None = None,
    admin_auth_service: AdminAuthService | None = None,
    access_grant_service: AccessGrantService | None = None,
    project_service: ProjectService | None = None,
    knowledge_document_service: KnowledgeDocumentService | None = None,
    ingestion_service: IngestionService | None = None,
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
        if authentication_service is None:
            repository = AdminUserRepository(cast(DatabaseSessionProvider, database_connection))
            redis_operations = cast(RedisOperations, redis_connection)
            authentication_service = AdminAuthService(
                repository,
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
        ingestion_queue: ArqJobQueue | None = None
        if document_processing_service is None:
            ingestion_queue = ArqJobQueue(
                application_settings.redis_url.get_secret_value(),
                timeout_seconds=application_settings.dependency_timeout_seconds,
            )
            document_processing_service = IngestionService(
                IngestionRepository(cast(DatabaseSessionProvider, database_connection)),
                ingestion_queue,
                dependency_timeout_seconds=application_settings.dependency_timeout_seconds,
            )

        async with AsyncExitStack() as stack:
            stack.push_async_callback(database_connection.close)
            stack.push_async_callback(redis_connection.close)
            if ingestion_queue is not None:
                stack.push_async_callback(ingestion_queue.close)
            application.state.settings = application_settings
            application.state.database = database_connection
            application.state.redis = redis_connection
            application.state.admin_auth_service = authentication_service
            application.state.access_grant_service = recruiter_access_service
            application.state.project_service = project_management_service
            application.state.knowledge_document_service = document_management_service
            application.state.ingestion_service = document_processing_service
            yield

    application = FastAPI(
        title=application_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    install_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(admin_auth_router)
    application.include_router(admin_access_grants_router)
    application.include_router(admin_documents_router)
    application.include_router(admin_ingestion_router)
    application.include_router(admin_projects_router)
    application.include_router(recruiter_access_router)
    return application


app = create_app()
