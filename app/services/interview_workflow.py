import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol, cast
from uuid import UUID, uuid4

from app.agent.graph import (
    EventSink,
    InterviewGraph,
    InterviewGraphState,
    InterviewGraphTimeoutError,
    initial_interview_state,
)
from app.agent.profile_agent import ProfileAgent
from app.agent.project_agent import ProjectAgent
from app.agent.schemas import FinalAnswerStatus
from app.agent.supervisor import InterviewSupervisorAgent
from app.agent.technical_agent import TechnicalAgent
from app.agent.tools import (
    ProfileAgentTools,
    ProjectAgentTools,
    SupervisorAgentTools,
    TechnicalAgentTools,
    VerificationAgentTools,
)
from app.agent.verification_agent import VerificationAgent
from app.core.config import Settings
from app.infrastructure.chat import ChatProvider, ChatProviderError
from app.infrastructure.health import DependencyUnavailableError
from app.infrastructure.interview_conversation import (
    ConversationExpiredError,
    ConversationOwnershipError,
    ConversationRequestStatus,
    ConversationTurn,
    InterviewConversationData,
    InterviewConversationStore,
)
from app.repositories.access_grant import (
    AccessGrantRepositoryUnavailableError,
    RequestQuotaRecord,
)
from app.schemas.access_grant import RecruiterPrincipal
from app.schemas.interview_conversation import (
    ConversationAskResponse,
    ConversationContext,
    ConversationCreateResponse,
    InterviewAgentTrace,
    InterviewPublicCitation,
)
from app.services.interview import RequestQuotaRepositoryBackend
from app.services.retrieval import (
    EmptyProjectScopeError,
    RetrievalService,
    RetrievalUnavailableError,
)

logger = logging.getLogger(__name__)


class InterviewGraphBackend(Protocol):
    async def run(self, initial_state: InterviewGraphState) -> InterviewGraphState: ...


GraphFactory = Callable[
    [RecruiterPrincipal, list[UUID], EventSink | None],
    InterviewGraphBackend,
]


class ConversationNotFoundError(Exception):
    pass


class ConversationBusyError(Exception):
    pass


class ConversationQuotaExhaustedError(Exception):
    pass


class ConversationPreviousRequestFailedError(Exception):
    pass


class ConversationRequestMismatchError(Exception):
    pass


class ConversationWorkflowUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Interview workflow is temporarily unavailable.")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InterviewWorkflowService:
    def __init__(
        self,
        quota_repository: RequestQuotaRepositoryBackend,
        conversation_store: InterviewConversationStore,
        *,
        retrieval_service: object,
        chat_provider: object,
        settings: Settings,
        graph_factory: GraphFactory | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._quota_repository = quota_repository
        self._conversation_store = conversation_store
        self._retrieval_service = retrieval_service
        self._chat_provider = chat_provider
        self._settings = settings
        self._graph_factory = graph_factory
        self._clock = clock

    async def create_conversation(
        self,
        *,
        principal: RecruiterPrincipal,
        session_token: str,
    ) -> ConversationCreateResponse:
        try:
            conversation = await self._conversation_store.create(
                session_token=session_token,
                grant_id=principal.grant_id,
                ttl_seconds=self._settings.conversation_ttl_seconds,
                expires_at_limit=principal.grant_expires_at,
            )
        except (ConversationExpiredError, DependencyUnavailableError) as error:
            raise ConversationWorkflowUnavailableError from error
        return ConversationCreateResponse(
            conversation_id=conversation.conversation_id,
            expires_at=conversation.expires_at,
            remaining_requests=principal.remaining_requests,
        )

    async def delete_conversation(
        self,
        *,
        principal: RecruiterPrincipal,
        session_token: str,
        conversation_id: UUID,
    ) -> None:
        try:
            deleted = await self._conversation_store.delete_owned(
                conversation_id,
                session_token=session_token,
                grant_id=principal.grant_id,
            )
        except ConversationOwnershipError as error:
            raise ConversationNotFoundError from error
        except DependencyUnavailableError as error:
            raise ConversationWorkflowUnavailableError from error
        if not deleted:
            raise ConversationNotFoundError

    async def ask(
        self,
        *,
        principal: RecruiterPrincipal,
        session_token: str,
        conversation_id: UUID,
        request_id: UUID,
        question: str,
        requested_project_ids: list[UUID] | None,
        event_sink: EventSink | None = None,
    ) -> ConversationAskResponse:
        normalized_question = question.strip()
        if not normalized_question or len(normalized_question) > 1_000:
            raise ValueError("Interview question is invalid.")
        conversation = await self._load_conversation(
            principal=principal,
            session_token=session_token,
            conversation_id=conversation_id,
        )
        try:
            effective_project_ids = RetrievalService.resolve_project_scope(
                principal.allowed_project_ids,
                requested_project_ids,
            )
        except EmptyProjectScopeError:
            return self._access_restricted(conversation, principal)

        question_hash = self._question_hash(normalized_question, effective_project_ids)
        existing = await self._conversation_store.read_request(conversation_id, request_id)
        cached = self._existing_request_response(existing, question_hash)
        if cached is not None:
            return cached

        lock_token = await self._conversation_store.acquire_turn_lock(
            conversation_id,
            ttl_seconds=max(30, int(self._settings.agent_run_timeout_seconds) + 15),
        )
        if lock_token is None:
            raise ConversationBusyError
        started = perf_counter()
        idempotency_started = False
        try:
            existing = await self._conversation_store.read_request(conversation_id, request_id)
            cached = self._existing_request_response(existing, question_hash)
            if cached is not None:
                return cached
            created, request_record = await self._conversation_store.begin_request(
                conversation_id,
                request_id=request_id,
                question_hash=question_hash,
                ttl_seconds=max(60, int(self._settings.agent_run_timeout_seconds * 2)),
            )
            if not created:
                cached = self._existing_request_response(request_record, question_hash)
                if cached is not None:
                    return cached
                raise ConversationBusyError
            idempotency_started = True

            quota = await self._consume_quota(principal.grant_id)
            if quota is None:
                await self._conversation_store.delete_request(conversation_id, request_id)
                idempotency_started = False
                raise ConversationQuotaExhaustedError

            graph = self._make_graph(principal, effective_project_ids, event_sink)
            initial_state = initial_interview_state(
                run_id=uuid4(),
                conversation_id=conversation_id,
                recruiter_session_id=self._conversation_store.session_fingerprint(session_token),
                grant_id=principal.grant_id,
                allowed_project_ids=principal.allowed_project_ids,
                effective_project_ids=effective_project_ids,
                question=normalized_question,
                recent_messages=self._recent_messages(conversation),
                conversation_summary=conversation.conversation_summary,
                remaining_requests=quota.remaining_requests,
            )
            initial_state["active_project_ids"] = conversation.active_project_ids
            initial_state["active_technical_topics"] = conversation.active_technical_topics
            result = await graph.run(initial_state)
            response = self._response_from_state(
                conversation,
                result,
                quota.remaining_requests,
            )
            await self._save_turn(
                conversation,
                session_token=session_token,
                question=normalized_question,
                response=response,
                state=result,
            )
            await self._conversation_store.complete_request(
                conversation_id,
                request_id=request_id,
                question_hash=question_hash,
                response_payload=response.model_dump(mode="json"),
                ttl_seconds=self._settings.conversation_ttl_seconds,
            )
            self._log_run(result, started, provider_error_type=None)
            return response
        except asyncio.CancelledError:
            if idempotency_started:
                await self._conversation_store.fail_request(
                    conversation_id,
                    request_id=request_id,
                    question_hash=question_hash,
                    error_code="request_cancelled",
                    ttl_seconds=self._settings.conversation_ttl_seconds,
                )
            raise
        except (
            ChatProviderError,
            RetrievalUnavailableError,
            InterviewGraphTimeoutError,
            DependencyUnavailableError,
        ) as error:
            if idempotency_started:
                await self._conversation_store.fail_request(
                    conversation_id,
                    request_id=request_id,
                    question_hash=question_hash,
                    error_code=type(error).__name__,
                    ttl_seconds=self._settings.conversation_ttl_seconds,
                )
            logger.warning(
                "interview_agent_run_failed",
                extra={
                    "conversation_id": str(conversation_id),
                    "provider_error_type": type(error).__name__,
                },
            )
            raise ConversationWorkflowUnavailableError from error
        finally:
            await self._conversation_store.release_turn_lock(conversation_id, lock_token)

    async def _load_conversation(
        self,
        *,
        principal: RecruiterPrincipal,
        session_token: str,
        conversation_id: UUID,
    ) -> InterviewConversationData:
        try:
            conversation = await self._conversation_store.read_owned(
                conversation_id,
                session_token=session_token,
                grant_id=principal.grant_id,
            )
        except ConversationOwnershipError as error:
            raise ConversationNotFoundError from error
        except DependencyUnavailableError as error:
            raise ConversationWorkflowUnavailableError from error
        if conversation is None:
            raise ConversationNotFoundError
        return conversation

    async def _consume_quota(self, grant_id: UUID) -> RequestQuotaRecord | None:
        try:
            return await self._quota_repository.consume_request(grant_id)
        except AccessGrantRepositoryUnavailableError as error:
            raise ConversationWorkflowUnavailableError from error

    def _make_graph(
        self,
        principal: RecruiterPrincipal,
        effective_project_ids: list[UUID],
        event_sink: EventSink | None,
    ) -> InterviewGraphBackend:
        if self._graph_factory is not None:
            return self._graph_factory(principal, effective_project_ids, event_sink)
        retrieval = cast(RetrievalService, self._retrieval_service)
        chat = cast(ChatProvider, self._chat_provider)
        profile = ProfileAgent(
            chat,
            ProfileAgentTools(retrieval, grant_id=principal.grant_id),
            max_tool_calls=self._settings.agent_profile_max_tool_calls,
            output_retries=self._settings.rag_answer_output_retries,
        )
        project = ProjectAgent(
            chat,
            ProjectAgentTools(
                retrieval,
                grant_id=principal.grant_id,
                effective_project_ids=effective_project_ids,
                authorized_projects={
                    item.id: item.name
                    for item in principal.allowed_projects
                    if item.id in set(effective_project_ids)
                },
            ),
            max_tool_calls=self._settings.agent_project_max_tool_calls,
            output_retries=self._settings.rag_answer_output_retries,
        )
        technical = TechnicalAgent(
            chat,
            TechnicalAgentTools(retrieval, grant_id=principal.grant_id),
            max_tool_calls=self._settings.agent_technical_max_tool_calls,
            output_retries=self._settings.rag_answer_output_retries,
        )
        verification = VerificationAgent(
            chat,
            VerificationAgentTools(
                retrieval,
                grant_id=principal.grant_id,
                allowed_project_ids=principal.allowed_project_ids,
                effective_project_ids=effective_project_ids,
            ),
            output_retries=self._settings.rag_answer_output_retries,
        )
        tools = SupervisorAgentTools(
            profile_runner=profile.run,
            project_runner=project.run,
            technical_runner=technical.run,
            verification_runner=verification.run,
        )
        supervisor = InterviewSupervisorAgent(
            chat,
            tools,
            max_specialist_calls=self._settings.agent_supervisor_max_specialist_calls,
            output_retries=self._settings.rag_answer_output_retries,
        )
        return InterviewGraph(
            supervisor,
            max_verification_runs=self._settings.agent_verification_max_runs,
            max_answer_repairs=self._settings.agent_max_answer_repairs,
            max_graph_steps=self._settings.agent_max_graph_steps,
            timeout_seconds=self._settings.agent_run_timeout_seconds,
            event_sink=event_sink,
        )

    def _response_from_state(
        self,
        conversation: InterviewConversationData,
        state: InterviewGraphState,
        remaining_requests: int,
    ) -> ConversationAskResponse:
        citations: list[InterviewPublicCitation] = []
        for handle in state["citations"]:
            item = state["evidence_registry"].get(handle)
            if item is None:
                continue
            citations.append(
                InterviewPublicCitation(
                    citation_handle=item.citation_handle,
                    knowledge_type=item.knowledge_type,
                    document_scope=item.document_scope,
                    knowledge_status=item.knowledge_status,
                    project_id=item.project_id,
                    project_name=item.project_name,
                    document_title=item.document_title,
                    version_number=item.version_number,
                    heading_path=item.heading_path,
                    excerpt=item.content.strip()[:500],
                )
            )
        return ConversationAskResponse(
            conversation_id=conversation.conversation_id,
            status=state["final_status"],
            answer=state["final_answer"],
            citations=citations,
            agent_trace=InterviewAgentTrace(
                agents_used=state["agents_used"],
                public_path=state["public_path"],
            ),
            context=ConversationContext(
                active_project_ids=state["active_project_ids"],
                active_technical_topics=state["active_technical_topics"],
                turn_number=conversation.turn_count + 1,
            ),
            remaining_requests=remaining_requests,
        )

    async def _save_turn(
        self,
        conversation: InterviewConversationData,
        *,
        session_token: str,
        question: str,
        response: ConversationAskResponse,
        state: InterviewGraphState,
    ) -> None:
        turn = ConversationTurn(
            question_summary=question[:1_000],
            answer_summary=response.answer[:2_000],
        )
        summary_piece = f"\nQ: {question[:300]}\nA: {response.answer[:700]}"
        summary = (conversation.conversation_summary + summary_piece)[
            -self._settings.conversation_summary_max_characters :
        ]
        updated = conversation.model_copy(
            update={
                "recent_turns": [*conversation.recent_turns, turn],
                "conversation_summary": summary,
                "active_project_ids": state["active_project_ids"],
                "active_technical_topics": state["active_technical_topics"],
                "turn_count": conversation.turn_count + 1,
                "updated_at": self._clock(),
            }
        )
        await self._conversation_store.save_owned(updated, session_token=session_token)

    @staticmethod
    def _recent_messages(conversation: InterviewConversationData) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for turn in conversation.recent_turns:
            messages.append({"role": "user", "summary": turn.question_summary})
            messages.append({"role": "assistant", "summary": turn.answer_summary})
        return messages

    @staticmethod
    def _question_hash(question: str, project_ids: list[UUID]) -> str:
        payload = json.dumps(
            {
                "question": question,
                "project_ids": [str(item) for item in project_ids],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _existing_request_response(
        request: object | None,
        question_hash: str,
    ) -> ConversationAskResponse | None:
        if request is None:
            return None
        record = cast(object, request)
        if getattr(record, "question_hash", None) != question_hash:
            raise ConversationRequestMismatchError
        status = getattr(record, "status", None)
        if status is ConversationRequestStatus.COMPLETED:
            payload = getattr(record, "response_payload", None)
            if not isinstance(payload, dict):
                raise ConversationPreviousRequestFailedError
            return ConversationAskResponse.model_validate(payload)
        if status is ConversationRequestStatus.FAILED:
            raise ConversationPreviousRequestFailedError
        if status is ConversationRequestStatus.PENDING:
            raise ConversationBusyError
        raise ConversationRequestMismatchError

    @staticmethod
    def _access_restricted(
        conversation: InterviewConversationData,
        principal: RecruiterPrincipal,
    ) -> ConversationAskResponse:
        return ConversationAskResponse(
            conversation_id=conversation.conversation_id,
            status=FinalAnswerStatus.ACCESS_RESTRICTED,
            answer=(
                "这个问题涉及当前没有开放的项目资料，我暂时不展开具体实现。"
                "不过可以结合目前授权的项目，介绍我在类似问题上的设计思路。"
            ),
            citations=[],
            agent_trace=InterviewAgentTrace(agents_used=[], public_path=[]),
            context=ConversationContext(
                active_project_ids=conversation.active_project_ids,
                active_technical_topics=conversation.active_technical_topics,
                turn_number=conversation.turn_count,
            ),
            remaining_requests=principal.remaining_requests,
        )

    @staticmethod
    def _log_run(
        state: InterviewGraphState,
        started: float,
        *,
        provider_error_type: str | None,
    ) -> None:
        logger.info(
            "interview_agent_run_completed",
            extra={
                "run_id": str(state["run_id"]),
                "conversation_id": str(state["conversation_id"]),
                "final_status": state["final_status"].value,
                "agents_used": state["agents_used"],
                "graph_steps": state["graph_step_count"],
                "llm_call_count": state["llm_call_count"],
                "tool_call_count": state["tool_call_count"],
                "answer_repair_count": state["repair_count"],
                "duration_ms": round((perf_counter() - started) * 1_000),
                "provider_error_type": provider_error_type,
                "citation_count": len(state["citations"]),
            },
        )
