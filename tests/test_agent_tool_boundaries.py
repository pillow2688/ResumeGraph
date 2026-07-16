from app.agent.tools import (
    ProfileToolName,
    ProjectToolName,
    SupervisorToolName,
    TechnicalToolName,
    VerificationToolName,
    tool_names_for_agent,
)


def test_each_agent_has_an_exact_private_tool_whitelist() -> None:
    assert tool_names_for_agent("supervisor") == {item.value for item in SupervisorToolName}
    assert tool_names_for_agent("profile_agent") == {item.value for item in ProfileToolName}
    assert tool_names_for_agent("project_agent") == {item.value for item in ProjectToolName}
    assert tool_names_for_agent("technical_agent") == {item.value for item in TechnicalToolName}
    assert tool_names_for_agent("verification_agent") == {
        item.value for item in VerificationToolName
    }


def test_agent_tool_sets_do_not_cross_privilege_boundaries() -> None:
    profile = tool_names_for_agent("profile_agent")
    project = tool_names_for_agent("project_agent")
    technical = tool_names_for_agent("technical_agent")
    verification = tool_names_for_agent("verification_agent")
    supervisor = tool_names_for_agent("supervisor")

    assert profile == {"get_profile_overview", "search_profile_knowledge"}
    assert project == {
        "list_authorized_projects",
        "get_project_overview",
        "search_project_knowledge",
    }
    assert technical == {"get_technical_topic_overview", "search_technical_knowledge"}
    assert verification == {
        "validate_citation_handles",
        "revalidate_evidence",
        "check_evidence_scope",
        "check_access_grant_scope",
    }
    assert supervisor == {
        "ask_profile_agent",
        "ask_project_agent",
        "ask_technical_agent",
        "ask_verification_agent",
    }
    assert not profile & project
    assert not technical & project
    assert not verification & (profile | project | technical)
    assert not supervisor & (profile | project | technical | verification)
