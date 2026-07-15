import asyncio
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from app.infrastructure.chat import ChatProvider, ChatProviderError
from app.rag.prompt import build_interview_prompts
from app.repositories.access_grant import (
    AccessGrantRepositoryUnavailableError,
    RequestQuotaRecord,
)
from app.schemas.access_grant import RecruiterPrincipal
from app.schemas.interview import (
    InterviewAskResponse,
    InterviewCitation,
    ModelInterviewAnswer,
)
from app.services.retrieval import (
    EmptyProjectScopeError,
    Evidence,
    RetrievalUnavailableError,
)

INSUFFICIENT_EVIDENCE_ANSWER = "我目前提供的资料中没有记录这一点，因此无法给出准确回答。"


class RequestQuotaRepositoryBackend(Protocol):
    async def consume_request(self, grant_id: UUID) -> RequestQuotaRecord | None: ...


class RetrievalServiceBackend(Protocol):
    @staticmethod
    def resolve_project_scope(
        allowed_project_ids: list[UUID],
        requested_project_ids: list[UUID] | None,
    ) -> list[UUID]: ...

    async def retrieve(
        self,
        *,
        query: str,
        grant_id: UUID,
        project_ids: list[UUID],
    ) -> list[Evidence]: ...

    async def revalidate(
        self,
        *,
        grant_id: UUID,
        project_ids: list[UUID],
        evidence: list[Evidence],
    ) -> set[str]: ...


class InterviewProjectScopeError(Exception):
    pass


class InterviewQuotaExhaustedError(Exception):
    pass


class InterviewOutputInvalidError(Exception):
    pass


class InterviewUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Interview answering is temporarily unavailable.")


class InterviewService:
    def __init__(
        self,
        quota_repository: RequestQuotaRepositoryBackend,
        retrieval_service: RetrievalServiceBackend,
        chat_provider: ChatProvider,
        *,
        output_retry_count: int,
        dependency_timeout_seconds: float,
    ) -> None:
        if not 0 <= output_retry_count <= 1:
            raise ValueError("Interview output retry count must be zero or one.")
        if dependency_timeout_seconds <= 0:
            raise ValueError("Interview timeout must be positive.")
        self._quota_repository = quota_repository
        self._retrieval_service = retrieval_service
        self._chat_provider = chat_provider
        self._output_retry_count = output_retry_count
        self._dependency_timeout_seconds = dependency_timeout_seconds

    async def ask(
        self,
        *,
        principal: RecruiterPrincipal,
        question: str,
        requested_project_ids: list[UUID] | None,
    ) -> InterviewAskResponse:
        try:
            effective_project_ids = self._retrieval_service.resolve_project_scope(
                principal.allowed_project_ids,
                requested_project_ids,
            )
        except EmptyProjectScopeError as error:
            raise InterviewProjectScopeError from error

        quota = await self._consume_quota(principal.grant_id)
        if quota is None:
            raise InterviewQuotaExhaustedError

        try:
            evidence = await self._retrieval_service.retrieve(
                query=question,
                grant_id=principal.grant_id,
                project_ids=effective_project_ids,
            )
        except RetrievalUnavailableError as error:
            raise InterviewUnavailableError from error
        if not evidence:
            return self._insufficient(quota.remaining_requests)

        system_prompt, user_prompt = build_interview_prompts(
            question=question,
            evidence=evidence,
        )
        valid_handles = {item.citation_handle for item in evidence}
        model_answer: ModelInterviewAnswer | None = None
        for attempt in range(self._output_retry_count + 1):
            retry_prompt = user_prompt
            if attempt:
                retry_prompt += (
                    "\n上一次输出未通过结构或引用校验。请仅使用提供的 Handle，重新返回严格 JSON。"
                )
            try:
                raw_output = await asyncio.wait_for(
                    self._chat_provider.complete_json(
                        system_prompt=system_prompt,
                        user_prompt=retry_prompt,
                    ),
                    timeout=self._dependency_timeout_seconds,
                )
            except (TimeoutError, ChatProviderError) as error:
                raise InterviewUnavailableError from error
            try:
                candidate = ModelInterviewAnswer.model_validate_json(raw_output)
            except ValidationError:
                continue
            if not set(candidate.citation_handles).issubset(valid_handles):
                continue
            model_answer = candidate
            break
        if model_answer is None:
            raise InterviewOutputInvalidError
        if model_answer.status == "insufficient_evidence":
            return self._insufficient(quota.remaining_requests)

        try:
            still_valid = await self._retrieval_service.revalidate(
                grant_id=principal.grant_id,
                project_ids=effective_project_ids,
                evidence=evidence,
            )
        except RetrievalUnavailableError as error:
            raise InterviewUnavailableError from error
        cited_handles = list(dict.fromkeys(model_answer.citation_handles))
        if not set(cited_handles).issubset(still_valid):
            return self._insufficient(quota.remaining_requests)

        evidence_by_handle = {item.citation_handle: item for item in evidence}
        citations = [self._public_citation(evidence_by_handle[handle]) for handle in cited_handles]
        return InterviewAskResponse(
            status="answered",
            answer=model_answer.answer,
            citations=citations,
            remaining_requests=quota.remaining_requests,
        )

    async def _consume_quota(self, grant_id: UUID) -> RequestQuotaRecord | None:
        try:
            return await asyncio.wait_for(
                self._quota_repository.consume_request(grant_id),
                timeout=self._dependency_timeout_seconds,
            )
        except (TimeoutError, AccessGrantRepositoryUnavailableError) as error:
            raise InterviewUnavailableError from error

    @staticmethod
    def _insufficient(remaining_requests: int) -> InterviewAskResponse:
        return InterviewAskResponse(
            status="insufficient_evidence",
            answer=INSUFFICIENT_EVIDENCE_ANSWER,
            citations=[],
            remaining_requests=remaining_requests,
        )

    @staticmethod
    def _public_citation(evidence: Evidence) -> InterviewCitation:
        return InterviewCitation(
            citation_handle=evidence.citation_handle,
            document_scope=evidence.document_scope,
            project_id=evidence.project_id,
            project_name=evidence.project_name,
            document_title=evidence.document_title,
            version_number=evidence.version_number,
            heading_path=list(evidence.heading_path),
        )
