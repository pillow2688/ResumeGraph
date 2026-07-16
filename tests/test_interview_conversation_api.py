from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.access_grant import ProjectSummary, RecruiterPrincipal
from app.schemas.interview_conversation import (
    ConversationAskResponse,
    ConversationContext,
    ConversationCreateResponse,
    InterviewAgentTrace,
    InterviewPublicCitation,
)
from app.services.access_grant import InvalidRecruiterSessionError

NOW = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)
PROJECT_ID = uuid4()
CONVERSATION_ID = uuid4()


class FakeHealthDependency:
    async def check_health(self) -> None:
        pass

    async def close(self) -> None:
        pass


class FakeAccessService:
    def __init__(self, principal: RecruiterPrincipal) -> None:
        self.principal = principal
        self.revoked = False

    async def get_current_recruiter_for_interview(self, session_token: str) -> RecruiterPrincipal:
        if session_token != "valid-recruiter-session" or self.revoked:
            raise InvalidRecruiterSessionError
        return self.principal


class FakeWorkflowService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def create_conversation(self, **kwargs: object) -> ConversationCreateResponse:
        self.calls.append(("create", kwargs))
        return ConversationCreateResponse(
            conversation_id=CONVERSATION_ID,
            expires_at=NOW + timedelta(hours=1),
            remaining_requests=20,
        )

    async def ask(self, **kwargs: object) -> ConversationAskResponse:
        self.calls.append(("ask", kwargs))
        sink = kwargs.get("event_sink")
        if sink is not None:
            await sink(
                {
                    "event_type": "question_received",
                    "public_message": "已收到问题",
                    "timestamp": NOW.isoformat(),
                    "progress": 0,
                }
            )
            await sink(
                {
                    "event_type": "routing_started",
                    "public_message": "正在理解问题",
                    "timestamp": NOW.isoformat(),
                    "progress": 5,
                }
            )
        return ConversationAskResponse(
            conversation_id=CONVERSATION_ID,
            status="answered_with_boundary",
            answer="我目前使用 Redis 保存 Session；缓存方案仍属于后续考虑。",
            citations=[
                InterviewPublicCitation(
                    citation_handle="evidence_1",
                    knowledge_type="project_fact",
                    document_scope="project",
                    knowledge_status="implemented",
                    project_id=PROJECT_ID,
                    project_name="ResumeGraph",
                    document_title="Redis usage",
                    version_number=1,
                    heading_path=["Redis"],
                    excerpt="Redis stores server-side sessions.",
                )
            ],
            agent_trace=InterviewAgentTrace(
                agents_used=["project_agent", "verification_agent"],
                public_path=["查询项目资料", "验证回答"],
            ),
            context=ConversationContext(
                active_project_ids=[PROJECT_ID],
                active_technical_topics=["Redis"],
                turn_number=1,
            ),
            remaining_requests=19,
        )

    async def delete_conversation(self, **kwargs: object) -> None:
        self.calls.append(("delete", kwargs))


def make_client():
    settings = Settings(
        environment="test",
        cookie_secure=False,
        database_url="postgresql+asyncpg://test:test@postgres/test",
        redis_url="redis://redis:6379/0",
        access_token_pepper="fictional-interview-api-pepper-value",
        _env_file=None,
    )
    principal = RecruiterPrincipal(
        grant_id=uuid4(),
        grant_name="Fictional grant",
        allowed_project_ids=[PROJECT_ID],
        grant_expires_at=NOW + timedelta(hours=1),
        remaining_requests=20,
        allowed_projects=[ProjectSummary(id=PROJECT_ID, name="ResumeGraph")],
    )
    access = FakeAccessService(principal)
    workflow = FakeWorkflowService()
    app = create_app(
        settings=settings,
        database=FakeHealthDependency(),
        redis=FakeHealthDependency(),
        admin_auth_service=object(),
        access_grant_service=access,
        project_service=object(),
        knowledge_document_service=object(),
        interview_service=object(),
        interview_workflow_service=workflow,
    )
    client = TestClient(app)
    client.cookies.set(
        settings.recruiter_session_cookie_name,
        "valid-recruiter-session",
        path="/api/v1",
    )
    return client, workflow, access


def test_conversation_create_non_stream_ask_and_delete() -> None:
    client, workflow, _access = make_client()
    request_id = uuid4()

    with client:
        created = client.post("/api/v1/interview/conversations")
        answer = client.post(
            f"/api/v1/interview/conversations/{CONVERSATION_ID}/ask",
            json={
                "request_id": str(request_id),
                "question": "Why Redis?",
                "project_ids": [str(PROJECT_ID)],
            },
        )
        deleted = client.delete(f"/api/v1/interview/conversations/{CONVERSATION_ID}")

    assert created.status_code == 201
    assert created.json()["conversation_id"] == str(CONVERSATION_ID)
    assert answer.status_code == 200
    assert answer.json()["status"] == "answered_with_boundary"
    assert answer.json()["citations"][0]["knowledge_type"] == "project_fact"
    assert answer.json()["agent_trace"]["public_path"] == [
        "查询项目资料",
        "验证回答",
    ]
    assert deleted.status_code == 204
    assert [name for name, _kwargs in workflow.calls] == ["create", "ask", "delete"]
    assert workflow.calls[1][1]["session_token"] == "valid-recruiter-session"


def test_post_sse_exposes_only_public_events_and_final_payload() -> None:
    client, _workflow, _access = make_client()

    with client:
        response = client.post(
            f"/api/v1/interview/conversations/{CONVERSATION_ID}/ask/stream",
            json={"request_id": str(uuid4()), "question": "Why Redis?"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert body.index("event: question_received") < body.index("event: routing_started")
    assert body.index("event: routing_started") < body.index("event: answer_completed")
    assert '"response": {' in body
    assert "answered_with_boundary" in body
    assert "Chain of Thought" not in body
    assert "system_prompt" not in body
    assert "reasoning_content" not in body
    assert "chunk_id" not in body
    assert "document_id" not in body


def test_invalid_question_and_revoked_grant_do_not_enter_workflow() -> None:
    client, workflow, access = make_client()

    with client:
        invalid = client.post(
            f"/api/v1/interview/conversations/{CONVERSATION_ID}/ask",
            json={"request_id": str(uuid4()), "question": "   "},
        )
        access.revoked = True
        revoked = client.post("/api/v1/interview/conversations")

    assert invalid.status_code == 422
    assert revoked.status_code == 401
    assert workflow.calls == []
