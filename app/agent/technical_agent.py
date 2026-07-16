from app.agent.prompts.technical_agent_prompt import SYSTEM_PROMPT
from app.agent.schemas import (
    AgentResultStatus,
    TechnicalAgentInput,
    TechnicalAgentLocalState,
    TechnicalAgentOutput,
    TechnicalAgentStep,
)
from app.agent.specialist_base import BoundedSpecialistAgent, SpecialistRun
from app.agent.tools import TechnicalAgentTools, ToolCallResult
from app.infrastructure.chat import ChatProvider


class TechnicalAgent(
    BoundedSpecialistAgent[TechnicalAgentOutput, TechnicalAgentLocalState, TechnicalAgentStep]
):
    prompt = SYSTEM_PROMPT
    step_schema = TechnicalAgentStep
    state_schema = TechnicalAgentLocalState
    available_tools = TechnicalAgentTools.allowed_tool_names

    def __init__(
        self,
        chat_provider: ChatProvider,
        tools: TechnicalAgentTools,
        *,
        max_tool_calls: int,
        output_retries: int,
    ) -> None:
        super().__init__(
            chat_provider,
            max_tool_calls=max_tool_calls,
            output_retries=output_retries,
        )
        self._tools = tools

    async def run(
        self,
        agent_input: TechnicalAgentInput,
    ) -> SpecialistRun[TechnicalAgentOutput, TechnicalAgentLocalState]:
        return await super().run(agent_input)

    async def _call_tool(self, step: TechnicalAgentStep) -> ToolCallResult:
        if step.tool_name is None:
            raise ValueError("Technical tool call is missing a tool name.")
        return await self._tools.call(step.tool_name, query=step.query)

    def _finish_output(
        self,
        step: TechnicalAgentStep,
        state: TechnicalAgentLocalState,
    ) -> TechnicalAgentOutput:
        evidence = self._selected_evidence(step, state)
        return TechnicalAgentOutput(
            status=self._status_for(evidence, step.missing_points),
            factual_summary=self._safe_summary(step, evidence),
            citation_handles=[item.citation_handle for item in evidence],
            evidence=evidence,
            missing_points=step.missing_points,
            project_implementation_requires_project_evidence=True,
        )

    def _budget_output(self, state: TechnicalAgentLocalState) -> TechnicalAgentOutput:
        evidence = list(state.evidence_registry.values())
        return TechnicalAgentOutput(
            status=AgentResultStatus.BUDGET_EXHAUSTED,
            factual_summary="已达到技术资料工具调用上限，只能基于当前通用知识提供有限说明。",
            citation_handles=list(state.evidence_registry),
            evidence=evidence,
            missing_points=["技术资料检索预算已用尽。"],
            project_implementation_requires_project_evidence=True,
        )

    def _error_output(self) -> TechnicalAgentOutput:
        return TechnicalAgentOutput(
            status=AgentResultStatus.ERROR,
            factual_summary="Technical Agent 未能生成有效的结构化结果。",
            citation_handles=[],
            evidence=[],
            missing_points=["结构化输出无效。"],
            project_implementation_requires_project_evidence=True,
        )
