from app.agent.prompts.profile_agent_prompt import SYSTEM_PROMPT
from app.agent.schemas import (
    AgentResultStatus,
    ProfileAgentInput,
    ProfileAgentLocalState,
    ProfileAgentOutput,
    ProfileAgentStep,
)
from app.agent.specialist_base import BoundedSpecialistAgent, SpecialistRun
from app.agent.tools import ProfileAgentTools, ToolCallResult
from app.infrastructure.chat import ChatProvider


class ProfileAgent(
    BoundedSpecialistAgent[ProfileAgentOutput, ProfileAgentLocalState, ProfileAgentStep]
):
    prompt = SYSTEM_PROMPT
    step_schema = ProfileAgentStep
    state_schema = ProfileAgentLocalState
    available_tools = ProfileAgentTools.allowed_tool_names

    def __init__(
        self,
        chat_provider: ChatProvider,
        tools: ProfileAgentTools,
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
        agent_input: ProfileAgentInput,
    ) -> SpecialistRun[ProfileAgentOutput, ProfileAgentLocalState]:
        return await super().run(agent_input)

    async def _call_tool(self, step: ProfileAgentStep) -> ToolCallResult:
        if step.tool_name is None:
            raise ValueError("Profile tool call is missing a tool name.")
        return await self._tools.call(step.tool_name, query=step.query)

    def _finish_output(
        self,
        step: ProfileAgentStep,
        state: ProfileAgentLocalState,
    ) -> ProfileAgentOutput:
        evidence = self._selected_evidence(step, state)
        return ProfileAgentOutput(
            status=self._status_for(evidence, step.missing_points),
            factual_summary=self._safe_summary(step, evidence),
            citation_handles=[item.citation_handle for item in evidence],
            evidence=evidence,
            missing_points=step.missing_points,
        )

    def _budget_output(self, state: ProfileAgentLocalState) -> ProfileAgentOutput:
        evidence = list(state.evidence_registry.values())
        return ProfileAgentOutput(
            status=AgentResultStatus.BUDGET_EXHAUSTED,
            factual_summary="已达到个人资料工具调用上限，只能基于当前检索结果提供有限回答。",
            citation_handles=list(state.evidence_registry),
            evidence=evidence,
            missing_points=["个人资料检索预算已用尽。"],
        )

    def _error_output(self) -> ProfileAgentOutput:
        return ProfileAgentOutput(
            status=AgentResultStatus.ERROR,
            factual_summary="个人资料 Agent 未能生成有效的结构化结果。",
            citation_handles=[],
            evidence=[],
            missing_points=["结构化输出无效。"],
        )
