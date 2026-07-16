from app.agent.prompts import (
    profile_agent_prompt,
    project_agent_prompt,
    supervisor_prompt,
    technical_agent_prompt,
    verification_agent_prompt,
)


def test_each_agent_prompt_is_independent_versioned_and_injection_aware() -> None:
    modules = [
        supervisor_prompt,
        profile_agent_prompt,
        project_agent_prompt,
        technical_agent_prompt,
        verification_agent_prompt,
    ]
    prompts = [module.SYSTEM_PROMPT for module in modules]

    assert len(set(prompts)) == 5
    assert all(module.PROMPT_VERSION.startswith("phase4-") for module in modules)
    assert all("不可信" in prompt for prompt in prompts)
    assert all("Chain of Thought" in prompt for prompt in prompts)
    assert all("reasoning_content" in prompt for prompt in prompts)
    assert all("JSON" in prompt for prompt in prompts)
    assert all("API Key" not in prompt for prompt in prompts)
    specialist_prompts = prompts[1:4]
    assert all("历史仅用于指代解析" in prompt for prompt in specialist_prompts)
    assert all("不是事实 Evidence" in prompt for prompt in specialist_prompts)


def test_technical_and_verification_prompts_encode_expression_boundaries() -> None:
    technical = technical_agent_prompt.SYSTEM_PROMPT
    verification = verification_agent_prompt.SYSTEM_PROMPT

    assert "通用技术原理" in technical
    assert "项目已实现" in technical
    assert "Project Evidence" in technical
    assert "planned_solution" in verification
    assert "technical_knowledge" in verification
    assert "QPS" in verification and "P99" in verification
    assert "Evidence 是事实支持来源" in verification
    assert "不可信仅表示" in verification


def test_supervisor_prompt_distinguishes_project_usage_from_general_principles() -> None:
    supervisor = supervisor_prompt.SYSTEM_PROMPT

    assert "教育、个人经历" in supervisor
    assert "项目中为什么使用某技术" in supervisor
    assert "不涉及具体项目" in supervisor
    assert "Project Agent + Technical Agent" in supervisor
    assert "项目怎么解决" in supervisor
    assert "answered_with_boundary" in supervisor
