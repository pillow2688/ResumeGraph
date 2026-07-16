from app.agent.prompts.project_agent_prompt import SYSTEM_PROMPT
from app.agent.schemas import (
    AgentResultStatus,
    KnowledgeType,
    ProjectAgentInput,
    ProjectAgentLocalState,
    ProjectAgentOutput,
    ProjectAgentStep,
)
from app.agent.specialist_base import BoundedSpecialistAgent, SpecialistRun
from app.agent.tools import ProjectAgentTools, ToolCallResult
from app.infrastructure.chat import ChatProvider


class ProjectAgent(
    BoundedSpecialistAgent[ProjectAgentOutput, ProjectAgentLocalState, ProjectAgentStep]
):
    prompt = SYSTEM_PROMPT
    step_schema = ProjectAgentStep
    state_schema = ProjectAgentLocalState
    available_tools = ProjectAgentTools.allowed_tool_names

    def __init__(
        self,
        chat_provider: ChatProvider,
        tools: ProjectAgentTools,
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
        agent_input: ProjectAgentInput,
    ) -> SpecialistRun[ProjectAgentOutput, ProjectAgentLocalState]:
        if agent_input.effective_project_ids != self._tools.effective_project_ids:
            raise ValueError("Project Agent input scope does not match its trusted tools.")
        return await super().run(agent_input)

    async def _call_tool(self, step: ProjectAgentStep) -> ToolCallResult:
        if step.tool_name is None:
            raise ValueError("Project tool call is missing a tool name.")
        return await self._tools.call(
            step.tool_name,
            query=step.query,
            requested_project_ids=step.project_ids,
        )

    def _finish_output(
        self,
        step: ProjectAgentStep,
        state: ProjectAgentLocalState,
    ) -> ProjectAgentOutput:
        evidence = self._selected_evidence(step, state)
        implemented = [
            item for item in evidence if item.knowledge_type is KnowledgeType.PROJECT_FACT
        ]
        planned = [
            item for item in evidence if item.knowledge_type is KnowledgeType.PLANNED_SOLUTION
        ]
        return ProjectAgentOutput(
            status=self._status_for(evidence, step.missing_points),
            factual_summary=self._safe_summary(step, evidence),
            citation_handles=[item.citation_handle for item in evidence],
            evidence=evidence,
            implemented_evidence=implemented,
            planned_evidence=planned,
            missing_points=step.missing_points,
        )

    def _budget_output(self, state: ProjectAgentLocalState) -> ProjectAgentOutput:
        evidence = list(state.evidence_registry.values())
        return ProjectAgentOutput(
            status=AgentResultStatus.BUDGET_EXHAUSTED,
            factual_summary="已达到项目资料工具调用上限，只能基于当前授权证据提供有限回答。",
            citation_handles=list(state.evidence_registry),
            evidence=evidence,
            implemented_evidence=[
                item for item in evidence if item.knowledge_type is KnowledgeType.PROJECT_FACT
            ],
            planned_evidence=[
                item for item in evidence if item.knowledge_type is KnowledgeType.PLANNED_SOLUTION
            ],
            missing_points=["项目资料检索预算已用尽。"],
        )

    def _error_output(self) -> ProjectAgentOutput:
        return ProjectAgentOutput(
            status=AgentResultStatus.ERROR,
            factual_summary="项目 Agent 未能生成有效的结构化结果。",
            citation_handles=[],
            evidence=[],
            implemented_evidence=[],
            planned_evidence=[],
            missing_points=["结构化输出无效。"],
        )
