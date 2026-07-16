import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.agent.schemas import (
    AgentEvidence,
    AgentName,
    FinalAnswerStatus,
    KnowledgeType,
    ProfileAgentInput,
    ProjectAgentInput,
    ProjectAgentOutput,
    RecentMessageInput,
    SpecialistAgentOutput,
    SupervisorAgentInput,
    SupervisorAgentLocalState,
    TechnicalAgentInput,
    VerificationAgentInput,
)
from app.agent.specialist_base import SpecialistRun
from app.agent.state import InterviewGraphState, PublicEventState
from app.agent.supervisor import InterviewSupervisorAgent
from app.agent.verification_agent import VerificationRun

EventSink = Callable[[PublicEventState], Awaitable[None]]


class InterviewGraphTimeoutError(RuntimeError):
    pass


def _event(event_type: str, public_message: str, progress: int) -> PublicEventState:
    return {
        "event_type": event_type,
        "public_message": public_message,
        "timestamp": datetime.now(UTC).isoformat(),
        "progress": progress,
    }


def initial_interview_state(
    *,
    run_id: UUID,
    conversation_id: UUID,
    recruiter_session_id: str,
    grant_id: UUID,
    allowed_project_ids: list[UUID],
    effective_project_ids: list[UUID],
    question: str,
    recent_messages: list[dict[str, str]],
    conversation_summary: str,
    remaining_requests: int,
) -> InterviewGraphState:
    return InterviewGraphState(
        run_id=run_id,
        conversation_id=conversation_id,
        recruiter_session_id=recruiter_session_id,
        grant_id=grant_id,
        allowed_project_ids=list(allowed_project_ids),
        effective_project_ids=list(effective_project_ids),
        current_question=question,
        recent_messages=recent_messages,
        conversation_summary=conversation_summary,
        active_project_ids=[],
        active_technical_topics=[],
        selected_agents=[],
        supervisor_decision=None,
        supervisor_draft=None,
        supervisor_local_state=SupervisorAgentLocalState(),
        agent_results={},
        evidence_registry={},
        draft_answer="",
        verification_result=None,
        final_answer="",
        final_status=FinalAnswerStatus.INSUFFICIENT_EVIDENCE,
        citations=[],
        remaining_requests=remaining_requests,
        tool_call_count=0,
        llm_call_count=0,
        graph_step_count=0,
        repair_count=0,
        verification_run_count=0,
        agents_used=[],
        public_path=[],
        budget_exhausted=False,
        public_events=[_event("question_received", "已收到问题", 0)],
    )


class InterviewGraph:
    def __init__(
        self,
        supervisor: InterviewSupervisorAgent,
        *,
        max_verification_runs: int,
        max_answer_repairs: int,
        max_graph_steps: int,
        timeout_seconds: float,
        event_sink: EventSink | None = None,
    ) -> None:
        if max_verification_runs <= 0:
            raise ValueError("Verification run budget must be positive.")
        if max_answer_repairs not in {0, 1}:
            raise ValueError("Answer repair budget must be zero or one.")
        if max_graph_steps < 5:
            raise ValueError("Graph step budget is too small.")
        if timeout_seconds <= 0:
            raise ValueError("Graph timeout must be positive.")
        self._supervisor = supervisor
        self._max_verification_runs = max_verification_runs
        self._max_answer_repairs = max_answer_repairs
        self._max_graph_steps = max_graph_steps
        self._timeout_seconds = timeout_seconds
        self._event_sink = event_sink

        builder = StateGraph(InterviewGraphState)
        builder.add_node("routing", self._routing_node)
        builder.add_node("specialists", self._specialists_node)
        builder.add_node("drafting", self._drafting_node)
        builder.add_node("verification", self._verification_node)
        builder.add_node("repair", self._repair_node)
        builder.add_node("finalize", self._finalize_node)
        builder.add_edge(START, "routing")
        builder.add_edge("routing", "specialists")
        builder.add_edge("specialists", "drafting")
        builder.add_edge("drafting", "verification")
        builder.add_conditional_edges(
            "verification",
            self._after_verification,
            {"repair": "repair", "finalize": "finalize"},
        )
        builder.add_edge("repair", "verification")
        builder.add_edge("finalize", END)
        self.compiled_graph = builder.compile()

    async def run(self, initial_state: InterviewGraphState) -> InterviewGraphState:
        if self._event_sink is not None:
            for event in initial_state["public_events"]:
                await self._event_sink(event)
        try:
            result = await asyncio.wait_for(
                self.compiled_graph.ainvoke(
                    initial_state,
                    config={"recursion_limit": self._max_graph_steps + 2},
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            raise InterviewGraphTimeoutError from error
        return cast(InterviewGraphState, result)

    async def _routing_node(self, state: InterviewGraphState) -> dict[str, object]:
        events = list(state["public_events"])
        events.append(await self._emit("routing_started", "正在理解问题", 5))
        route = await self._supervisor.route(self._supervisor_input(state))
        events.append(await self._emit("routing_completed", "已确定回答路径", 15))
        return {
            "supervisor_decision": route.decision,
            "selected_agents": route.decision.selected_agents,
            "active_project_ids": route.decision.target_project_ids,
            "active_technical_topics": route.decision.technical_topics,
            "llm_call_count": state["llm_call_count"] + route.llm_call_count,
            "graph_step_count": state["graph_step_count"] + 1,
            "public_events": events,
        }

    async def _specialists_node(self, state: InterviewGraphState) -> dict[str, object]:
        decision = state["supervisor_decision"]
        assert decision is not None
        events = list(state["public_events"])
        results: dict[str, SpecialistAgentOutput] = {}
        registry: dict[str, AgentEvidence] = {}
        supervisor_state = state["supervisor_local_state"].model_copy(deep=True)
        tool_calls = state["tool_call_count"]
        llm_calls = state["llm_call_count"]
        agents_used = list(state["agents_used"])
        public_path = list(state["public_path"])
        recent_context = self._recent_context(state)

        metadata = {
            AgentName.PROFILE: (
                "profile_search_started",
                "正在查询个人资料",
                "profile_search_completed",
                "个人资料查询完成",
                "查询个人资料",
            ),
            AgentName.PROJECT: (
                "project_search_started",
                "正在查询项目资料",
                "project_search_completed",
                "项目资料查询完成",
                "查询项目资料",
            ),
            AgentName.TECHNICAL: (
                "technical_search_started",
                "正在补充技术原理",
                "technical_search_completed",
                "技术原理查询完成",
                "补充技术原理",
            ),
        }
        for agent_name in decision.selected_agents:
            started, started_message, completed, completed_message, path = metadata[agent_name]
            events.append(await self._emit(started, started_message, 25))
            if agent_name is AgentName.PROFILE:
                agent_input: object = ProfileAgentInput(
                    question=state["current_question"],
                    recent_context=recent_context,
                )
            elif agent_name is AgentName.PROJECT:
                agent_input = ProjectAgentInput(
                    question=state["current_question"],
                    recent_context=recent_context,
                    effective_project_ids=state["effective_project_ids"],
                    needs_comparison=decision.needs_comparison,
                )
            else:
                agent_input = TechnicalAgentInput(
                    question=state["current_question"],
                    recent_context=recent_context,
                    technical_topics=decision.technical_topics,
                )
            specialist_result = await self._supervisor.ask_specialist(
                agent_name,
                agent_input,
                supervisor_state,
            )
            if specialist_result is None:
                break
            run = cast(SpecialistRun, specialist_result)
            output = self._register_output(run.output, registry)
            results[agent_name.value] = output
            tool_calls += 1 + run.local_state.tool_call_count
            llm_calls += run.local_state.llm_call_count
            agents_used.append(agent_name.value)
            public_path.append(path)
            events.append(await self._emit(completed, completed_message, 55))
        return {
            "agent_results": results,
            "evidence_registry": registry,
            "supervisor_local_state": supervisor_state,
            "tool_call_count": tool_calls,
            "llm_call_count": llm_calls,
            "agents_used": agents_used,
            "public_path": public_path,
            "graph_step_count": state["graph_step_count"] + 1,
            "public_events": events,
        }

    async def _drafting_node(self, state: InterviewGraphState) -> dict[str, object]:
        events = list(state["public_events"])
        events.append(await self._emit("answer_drafting", "正在生成回答草稿", 70))
        draft = await self._supervisor.draft(
            self._supervisor_input(state),
            agent_results=state["agent_results"],
            evidence_registry=state["evidence_registry"],
        )
        return {
            "supervisor_draft": draft.output,
            "draft_answer": draft.output.answer,
            "final_status": draft.output.status,
            "citations": draft.output.citation_handles,
            "llm_call_count": state["llm_call_count"] + draft.llm_call_count,
            "graph_step_count": state["graph_step_count"] + 1,
            "public_events": events,
        }

    async def _verification_node(self, state: InterviewGraphState) -> dict[str, object]:
        events = list(state["public_events"])
        events.append(await self._emit("verification_started", "正在验证回答", 82))
        verification = await self._supervisor.ask_verification(
            VerificationAgentInput(
                question=state["current_question"],
                draft_answer=state["draft_answer"],
                citation_handles=state["citations"],
                evidence=list(state["evidence_registry"].values()),
            )
        )
        run = cast(VerificationRun, verification)
        events.append(await self._emit("verification_completed", "回答验证完成", 90))
        agents_used = list(state["agents_used"])
        public_path = list(state["public_path"])
        if AgentName.VERIFICATION.value not in agents_used:
            agents_used.append(AgentName.VERIFICATION.value)
            public_path.append("验证回答")
        return {
            "verification_result": run.output,
            "verification_run_count": state["verification_run_count"] + 1,
            "tool_call_count": state["tool_call_count"] + 1 + run.local_state.tool_call_count,
            "llm_call_count": state["llm_call_count"] + run.local_state.llm_call_count,
            "agents_used": agents_used,
            "public_path": public_path,
            "graph_step_count": state["graph_step_count"] + 1,
            "public_events": events,
        }

    async def _repair_node(self, state: InterviewGraphState) -> dict[str, object]:
        verification = state["verification_result"]
        assert verification is not None
        events = list(state["public_events"])
        events.append(await self._emit("answer_repairing", "正在修正回答边界", 92))
        repaired = await self._supervisor.draft(
            self._supervisor_input(state),
            agent_results=state["agent_results"],
            evidence_registry=state["evidence_registry"],
            repair_instruction=verification.repair_instruction,
        )
        return {
            "supervisor_draft": repaired.output,
            "draft_answer": repaired.output.answer,
            "final_status": repaired.output.status,
            "citations": repaired.output.citation_handles,
            "repair_count": state["repair_count"] + 1,
            "llm_call_count": state["llm_call_count"] + repaired.llm_call_count,
            "graph_step_count": state["graph_step_count"] + 1,
            "public_events": events,
        }

    async def _finalize_node(self, state: InterviewGraphState) -> dict[str, object]:
        verification = state["verification_result"]
        passed = verification is not None and verification.passed
        if passed:
            final_answer = state["draft_answer"]
            final_status = state["final_status"]
            citations = state["citations"]
        elif state["evidence_registry"]:
            final_answer = (
                "现有资料只能确认其中一部分。为避免把技术原理或后续规划描述为已实现，"
                "我暂不扩展未经验证的结论。"
            )
            final_status = FinalAnswerStatus.PARTIAL_ANSWER
            citations = []
        else:
            final_answer = "这部分在目前授权发布的资料中没有足够记录，我不希望给出不准确的结论。"
            final_status = FinalAnswerStatus.INSUFFICIENT_EVIDENCE
            citations = []
        events = list(state["public_events"])
        events.append(await self._emit("answer_completed", "回答已完成", 100))
        return {
            "final_answer": final_answer,
            "final_status": final_status,
            "citations": citations,
            "graph_step_count": state["graph_step_count"] + 1,
            "public_events": events,
        }

    def _after_verification(self, state: InterviewGraphState) -> str:
        verification = state["verification_result"]
        if verification is not None and verification.passed:
            return "finalize"
        if self.can_repair(
            graph_step_count=state["graph_step_count"],
            max_graph_steps=self._max_graph_steps,
            repair_count=state["repair_count"],
            max_answer_repairs=self._max_answer_repairs,
            verification_run_count=state["verification_run_count"],
            max_verification_runs=self._max_verification_runs,
        ):
            return "repair"
        return "finalize"

    @staticmethod
    def can_repair(
        *,
        graph_step_count: int,
        max_graph_steps: int,
        repair_count: int,
        max_answer_repairs: int,
        verification_run_count: int,
        max_verification_runs: int,
    ) -> bool:
        return (
            repair_count < max_answer_repairs
            and verification_run_count < max_verification_runs
            and graph_step_count + 3 <= max_graph_steps
        )

    def _supervisor_input(self, state: InterviewGraphState) -> SupervisorAgentInput:
        return SupervisorAgentInput(
            question=state["current_question"],
            recent_messages=[RecentMessageInput(**item) for item in state["recent_messages"]],
            conversation_summary=state["conversation_summary"],
            allowed_project_ids=state["allowed_project_ids"],
            effective_project_ids=state["effective_project_ids"],
            active_project_ids=state["active_project_ids"],
            active_technical_topics=state["active_technical_topics"],
        )

    @staticmethod
    def _recent_context(state: InterviewGraphState) -> str:
        lines = [state["conversation_summary"]]
        lines.extend(
            f"{message['role']}: {message['summary']}" for message in state["recent_messages"]
        )
        return "\n".join(item for item in lines if item)[-4_000:]

    @staticmethod
    def _register_output(
        output: SpecialistAgentOutput,
        registry: dict[str, AgentEvidence],
    ) -> SpecialistAgentOutput:
        handle_map: dict[str, str] = {}
        for item in output.evidence:
            existing = next(
                (
                    registered
                    for registered in registry.values()
                    if registered.chunk_id == item.chunk_id
                ),
                None,
            )
            if existing is None:
                handle = f"evidence_{len(registry) + 1}"
                existing = item.model_copy(update={"citation_handle": handle})
                registry[handle] = existing
            handle_map[item.citation_handle] = existing.citation_handle
        citation_handles = list(
            dict.fromkeys(
                handle_map[handle] for handle in output.citation_handles if handle in handle_map
            )
        )
        evidence = [registry[handle] for handle in citation_handles]
        updates: dict[str, object] = {
            "citation_handles": citation_handles,
            "evidence": evidence,
        }
        if isinstance(output, ProjectAgentOutput):
            updates["implemented_evidence"] = [
                item for item in evidence if item.knowledge_type is KnowledgeType.PROJECT_FACT
            ]
            updates["planned_evidence"] = [
                item for item in evidence if item.knowledge_type is KnowledgeType.PLANNED_SOLUTION
            ]
        return output.model_copy(update=updates)

    async def _emit(
        self,
        event_type: str,
        public_message: str,
        progress: int,
    ) -> PublicEventState:
        event = _event(event_type, public_message, progress)
        if self._event_sink is not None:
            await self._event_sink(event)
        return event
