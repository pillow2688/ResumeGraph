from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.access_grant import ProjectSummary, RecruiterPrincipal
from app.schemas.interview import InterviewAskResponse, InterviewCitation
from app.services.access_grant import InvalidRecruiterSessionError
from app.services.interview import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    InterviewOutputInvalidError,
    InterviewProjectScopeError,
    InterviewQuotaExhaustedError,
    InterviewUnavailableError,
)


class FakeHealthDependency:
    async def close(self) -> None:
        pass


class FakeAccessService:
    def __init__(self, principal: RecruiterPrincipal) -> None:
        self.principal = principal
        self.invalid = False
        self.calls: list[str] = []

    async def get_current_recruiter_for_interview(
        self,
        session_token: str,
    ) -> RecruiterPrincipal:
        self.calls.append(session_token)
        if self.invalid:
            raise InvalidRecruiterSessionError
        return self.principal


class FakeInterviewService:
    def __init__(self, result: InterviewAskResponse) -> None:
        self.result = result
        self.error: Exception | None = None
        self.calls: list[dict[str, object]] = []

    async def ask(self, **kwargs: object) -> InterviewAskResponse:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def make_principal(*, remaining_requests: int = 20) -> RecruiterPrincipal:
    project_id = uuid4()
    return RecruiterPrincipal(
        grant_id=uuid4(),
        grant_name="Fictional Grant",
        allowed_project_ids=[project_id],
        grant_expires_at=datetime.now(UTC) + timedelta(days=7),
        remaining_requests=remaining_requests,
        allowed_projects=[ProjectSummary(id=project_id, name="ResumeGraph")],
    )


def make_client(*, remaining_requests: int = 20):
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://test:test@postgres/test",
        redis_url="redis://redis:6379/0",
        access_token_pepper="fictional-interview-pepper-at-least-thirty-two-characters",
        dependency_timeout_seconds=1,
        _env_file=None,
    )
    principal = make_principal(remaining_requests=remaining_requests)
    access = FakeAccessService(principal)
    interview = FakeInterviewService(
        InterviewAskResponse(
            status="answered",
            answer="我使用 Redis 保存短期 Session。",
            citations=[
                InterviewCitation(
                    citation_handle="evidence_1",
                    document_scope="project",
                    project_id=principal.allowed_project_ids[0],
                    project_name="ResumeGraph",
                    document_title="项目设计文档",
                    version_number=1,
                    heading_path=["状态管理", "Redis"],
                )
            ],
            remaining_requests=max(remaining_requests - 1, 0),
        )
    )
    app = create_app(
        settings=settings,
        database=FakeHealthDependency(),
        redis=FakeHealthDependency(),
        access_grant_service=access,  # type: ignore[arg-type]
        interview_service=interview,  # type: ignore[arg-type]
    )
    return TestClient(app), access, interview, settings, principal


def authenticate(client: TestClient, settings: Settings) -> None:
    client.cookies.set(
        settings.recruiter_session_cookie_name,
        "opaque-session-token",
        path="/api/v1",
    )


def test_missing_recruiter_session_cannot_ask() -> None:
    client, access, interview, _settings, _principal = make_client()

    with client:
        response = client.post("/api/v1/interview/ask", json={"question": "为什么使用 Redis？"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "recruiter_authentication_required"
    assert access.calls == []
    assert interview.calls == []


def test_revoked_or_expired_session_is_rejected_before_interview_service() -> None:
    client, access, interview, settings, _principal = make_client()
    access.invalid = True
    authenticate(client, settings)

    with client:
        response = client.post("/api/v1/interview/ask", json={"question": "为什么使用 Redis？"})

    assert response.status_code == 401
    assert interview.calls == []


def test_valid_request_passes_revalidated_principal_and_optional_scope() -> None:
    client, _access, interview, settings, principal = make_client()
    authenticate(client, settings)
    project_id = principal.allowed_project_ids[0]

    with client:
        response = client.post(
            "/api/v1/interview/ask",
            json={"question": "  为什么使用 Redis？  ", "project_ids": [str(project_id)]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "answered",
        "answer": "我使用 Redis 保存短期 Session。",
        "citations": [
            {
                "citation_handle": "evidence_1",
                "document_scope": "project",
                "project_id": str(project_id),
                "project_name": "ResumeGraph",
                "document_title": "项目设计文档",
                "version_number": 1,
                "heading_path": ["状态管理", "Redis"],
            }
        ],
        "remaining_requests": 19,
    }
    assert interview.calls[0]["principal"] == principal
    assert interview.calls[0]["question"] == "为什么使用 Redis？"
    assert interview.calls[0]["requested_project_ids"] == [project_id]


def test_parameter_errors_do_not_reach_interview_service() -> None:
    client, _access, interview, settings, _principal = make_client()
    authenticate(client, settings)

    with client:
        blank = client.post("/api/v1/interview/ask", json={"question": "   "})
        too_long = client.post("/api/v1/interview/ask", json={"question": "x" * 2001})
        empty_scope = client.post(
            "/api/v1/interview/ask",
            json={"question": "question", "project_ids": []},
        )

    assert [blank.status_code, too_long.status_code, empty_scope.status_code] == [422, 422, 422]
    assert interview.calls == []


def test_project_scope_quota_and_provider_errors_have_distinct_sanitized_responses() -> None:
    client, _access, interview, settings, _principal = make_client()
    authenticate(client, settings)
    cases = [
        (InterviewProjectScopeError(), 403, "project_scope_forbidden"),
        (InterviewQuotaExhaustedError(), 429, "request_quota_exhausted"),
        (InterviewOutputInvalidError("raw model output"), 503, "interview_unavailable"),
        (InterviewUnavailableError(), 503, "interview_unavailable"),
    ]

    with client:
        for error, expected_status, expected_code in cases:
            interview.error = error
            response = client.post(
                "/api/v1/interview/ask",
                json={"question": "为什么使用 Redis？"},
            )
            assert response.status_code == expected_status
            assert response.json()["error"]["code"] == expected_code
            assert "raw model output" not in response.text


def test_insufficient_evidence_response_has_fixed_answer_and_no_citations() -> None:
    client, _access, interview, settings, _principal = make_client()
    authenticate(client, settings)
    interview.result = InterviewAskResponse(
        status="insufficient_evidence",
        answer=INSUFFICIENT_EVIDENCE_ANSWER,
        citations=[],
        remaining_requests=19,
    )

    with client:
        response = client.post(
            "/api/v1/interview/ask",
            json={"question": "资料中不存在的性能指标？"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["answer"] == INSUFFICIENT_EVIDENCE_ANSWER
    assert response.json()["citations"] == []
