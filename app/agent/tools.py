from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from app.services.retrieval import Evidence

if TYPE_CHECKING:
    from app.agent.schemas import AgentEvidence


class SupervisorToolName(StrEnum):
    ASK_PROFILE = "ask_profile_agent"
    ASK_PROJECT = "ask_project_agent"
    ASK_TECHNICAL = "ask_technical_agent"
    ASK_VERIFICATION = "ask_verification_agent"


class ProfileToolName(StrEnum):
    GET_OVERVIEW = "get_profile_overview"
    SEARCH = "search_profile_knowledge"


class ProjectToolName(StrEnum):
    LIST_AUTHORIZED = "list_authorized_projects"
    GET_OVERVIEW = "get_project_overview"
    SEARCH = "search_project_knowledge"


class TechnicalToolName(StrEnum):
    GET_OVERVIEW = "get_technical_topic_overview"
    SEARCH = "search_technical_knowledge"


class VerificationToolName(StrEnum):
    VALIDATE_HANDLES = "validate_citation_handles"
    REVALIDATE_EVIDENCE = "revalidate_evidence"
    CHECK_EVIDENCE_SCOPE = "check_evidence_scope"
    CHECK_GRANT_SCOPE = "check_access_grant_scope"


ToolOwner = Literal[
    "supervisor",
    "profile_agent",
    "project_agent",
    "technical_agent",
    "verification_agent",
]


def tool_names_for_agent(agent: ToolOwner) -> set[str]:
    tool_sets: dict[ToolOwner, type[Enum]] = {
        "supervisor": SupervisorToolName,
        "profile_agent": ProfileToolName,
        "project_agent": ProjectToolName,
        "technical_agent": TechnicalToolName,
        "verification_agent": VerificationToolName,
    }
    try:
        enum_type = tool_sets[agent]
    except KeyError as error:
        raise ValueError("Unknown agent tool owner.") from error
    return {str(item.value) for item in enum_type}


class AgentRetrievalBackend(Protocol):
    async def search_profile_knowledge(
        self,
        *,
        query: str,
        grant_id: UUID,
    ) -> list[Evidence]: ...

    async def search_project_knowledge(
        self,
        *,
        query: str,
        grant_id: UUID,
        project_ids: list[UUID],
    ) -> list[Evidence]: ...

    async def search_technical_knowledge(
        self,
        *,
        query: str,
        grant_id: UUID,
    ) -> list[Evidence]: ...

    async def revalidate(
        self,
        *,
        grant_id: UUID,
        project_ids: list[UUID],
        evidence: list[Evidence],
    ) -> set[str]: ...


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    payload: dict[str, object]
    evidence: list[Evidence]


class ProfileAgentTools:
    allowed_tool_names = frozenset(item.value for item in ProfileToolName)

    def __init__(self, retrieval: AgentRetrievalBackend, *, grant_id: UUID) -> None:
        self._retrieval = retrieval
        self._grant_id = grant_id

    async def call(self, tool_name: ProfileToolName, *, query: str | None) -> ToolCallResult:
        if tool_name not in ProfileToolName:
            raise ValueError("Profile tool is not allowed.")
        effective_query = query or ("候选人教育背景、个人简介、技能、获奖、研究方向和求职方向概览")
        evidence = await self._retrieval.search_profile_knowledge(
            query=effective_query,
            grant_id=self._grant_id,
        )
        return ToolCallResult(payload={"result_kind": "profile_evidence"}, evidence=evidence)


class ProjectAgentTools:
    allowed_tool_names = frozenset(item.value for item in ProjectToolName)

    def __init__(
        self,
        retrieval: AgentRetrievalBackend,
        *,
        grant_id: UUID,
        effective_project_ids: list[UUID],
        authorized_projects: dict[UUID, str],
    ) -> None:
        self._retrieval = retrieval
        self._grant_id = grant_id
        self._effective_project_ids = list(dict.fromkeys(effective_project_ids))
        effective_set = set(self._effective_project_ids)
        self._authorized_projects = {
            project_id: name
            for project_id, name in authorized_projects.items()
            if project_id in effective_set
        }

    @property
    def effective_project_ids(self) -> list[UUID]:
        return list(self._effective_project_ids)

    async def call(
        self,
        tool_name: ProjectToolName,
        *,
        query: str | None,
        requested_project_ids: list[UUID],
    ) -> ToolCallResult:
        if tool_name is ProjectToolName.LIST_AUTHORIZED:
            projects = [
                {
                    "project_id": str(project_id),
                    "project_name": self._authorized_projects[project_id],
                }
                for project_id in self._effective_project_ids
                if project_id in self._authorized_projects
            ]
            return ToolCallResult(payload={"authorized_projects": projects}, evidence=[])

        requested = set(requested_project_ids)
        project_ids = (
            [item for item in self._effective_project_ids if item in requested]
            if requested_project_ids
            else list(self._effective_project_ids)
        )
        if not project_ids:
            return ToolCallResult(
                payload={"result_kind": "project_evidence", "scope_empty": True},
                evidence=[],
            )
        effective_query = query or "授权项目的职责、架构、实现、不足和后续规划概览"
        evidence = await self._retrieval.search_project_knowledge(
            query=effective_query,
            grant_id=self._grant_id,
            project_ids=project_ids,
        )
        return ToolCallResult(
            payload={
                "result_kind": "project_evidence",
                "project_ids": [str(item) for item in project_ids],
            },
            evidence=evidence,
        )


class TechnicalAgentTools:
    allowed_tool_names = frozenset(item.value for item in TechnicalToolName)

    def __init__(self, retrieval: AgentRetrievalBackend, *, grant_id: UUID) -> None:
        self._retrieval = retrieval
        self._grant_id = grant_id

    async def call(self, tool_name: TechnicalToolName, *, query: str | None) -> ToolCallResult:
        if tool_name not in TechnicalToolName:
            raise ValueError("Technical tool is not allowed.")
        effective_query = query or "相关通用技术原理、适用场景、风险和常见处理方式"
        evidence = await self._retrieval.search_technical_knowledge(
            query=effective_query,
            grant_id=self._grant_id,
        )
        return ToolCallResult(payload={"result_kind": "technical_evidence"}, evidence=evidence)


class VerificationAgentTools:
    allowed_tool_names = frozenset(item.value for item in VerificationToolName)

    def __init__(
        self,
        retrieval: AgentRetrievalBackend,
        *,
        grant_id: UUID,
        allowed_project_ids: list[UUID],
        effective_project_ids: list[UUID],
    ) -> None:
        self._retrieval = retrieval
        self._grant_id = grant_id
        self._allowed_project_ids = list(dict.fromkeys(allowed_project_ids))
        self._effective_project_ids = list(dict.fromkeys(effective_project_ids))

    def validate_citation_handles(
        self,
        requested_handles: list[str],
        evidence: list[AgentEvidence],
    ) -> tuple[list[str], list[str]]:
        registered = {item.citation_handle for item in evidence}
        valid = [handle for handle in requested_handles if handle in registered]
        invalid = [handle for handle in requested_handles if handle not in registered]
        return list(dict.fromkeys(valid)), list(dict.fromkeys(invalid))

    async def revalidate_evidence(self, evidence: list[AgentEvidence]) -> set[str]:
        service_evidence = [
            Evidence(
                citation_handle=item.citation_handle,
                chunk_id=item.chunk_id,
                content=item.content,
                content_hash=item.content_hash,
                document_scope=item.document_scope.value,
                project_id=item.project_id,
                project_name=item.project_name,
                document_id=item.document_id,
                document_title=item.document_title,
                version_number=item.version_number,
                heading_path=tuple(item.heading_path),
                distance=item.distance,
                knowledge_status=item.knowledge_status.value,
                knowledge_type=item.knowledge_type.value,
            )
            for item in evidence
        ]
        return await self._retrieval.revalidate(
            grant_id=self._grant_id,
            project_ids=self._effective_project_ids,
            evidence=service_evidence,
        )

    def check_evidence_scope(self, evidence: list[AgentEvidence]) -> list[str]:
        from app.agent.schemas import DocumentScope, KnowledgeStatus, KnowledgeType

        valid_combinations = {
            (
                DocumentScope.PROFILE,
                KnowledgeStatus.IMPLEMENTED,
                KnowledgeType.PROFILE_FACT,
            ),
            (
                DocumentScope.PROJECT,
                KnowledgeStatus.IMPLEMENTED,
                KnowledgeType.PROJECT_FACT,
            ),
            (
                DocumentScope.PROJECT,
                KnowledgeStatus.PLANNED,
                KnowledgeType.PLANNED_SOLUTION,
            ),
            (
                DocumentScope.TECHNICAL,
                KnowledgeStatus.GENERAL_KNOWLEDGE,
                KnowledgeType.TECHNICAL_KNOWLEDGE,
            ),
        }
        effective = set(self._effective_project_ids)
        violations: list[str] = []
        for item in evidence:
            combination = (item.document_scope, item.knowledge_status, item.knowledge_type)
            if combination not in valid_combinations:
                violations.append(f"Evidence scope/type mismatch: {item.citation_handle}.")
            if item.document_scope is DocumentScope.PROJECT:
                if item.project_id is None or item.project_id not in effective:
                    violations.append(f"Project scope violation: {item.citation_handle}.")
            elif item.project_id is not None:
                violations.append(f"Global evidence has a project: {item.citation_handle}.")
        return list(dict.fromkeys(violations))

    def check_access_grant_scope(self, evidence: list[AgentEvidence]) -> list[str]:
        from app.agent.schemas import DocumentScope

        allowed = set(self._allowed_project_ids)
        effective = set(self._effective_project_ids)
        violations: list[str] = []
        if not effective <= allowed:
            violations.append("Effective project scope exceeds the Access Grant scope.")
        for item in evidence:
            if item.document_scope is DocumentScope.PROJECT and item.project_id not in allowed:
                violations.append(f"Access Grant scope violation: {item.citation_handle}.")
        return list(dict.fromkeys(violations))


class SupervisorAgentTools:
    allowed_tool_names = frozenset(item.value for item in SupervisorToolName)

    def __init__(
        self,
        *,
        profile_runner: Callable[[object], Awaitable[object]] | None = None,
        project_runner: Callable[[object], Awaitable[object]] | None = None,
        technical_runner: Callable[[object], Awaitable[object]] | None = None,
        verification_runner: Callable[[object], Awaitable[object]] | None = None,
    ) -> None:
        self._profile_runner = profile_runner
        self._project_runner = project_runner
        self._technical_runner = technical_runner
        self._verification_runner = verification_runner

    async def ask_profile_agent(self, agent_input: object) -> object:
        if self._profile_runner is None:
            raise RuntimeError("Profile Agent tool is unavailable.")
        return await self._profile_runner(agent_input)

    async def ask_project_agent(self, agent_input: object) -> object:
        if self._project_runner is None:
            raise RuntimeError("Project Agent tool is unavailable.")
        return await self._project_runner(agent_input)

    async def ask_technical_agent(self, agent_input: object) -> object:
        if self._technical_runner is None:
            raise RuntimeError("Technical Agent tool is unavailable.")
        return await self._technical_runner(agent_input)

    async def ask_verification_agent(self, agent_input: object) -> object:
        if self._verification_runner is None:
            raise RuntimeError("Verification Agent tool is unavailable.")
        return await self._verification_runner(agent_input)
