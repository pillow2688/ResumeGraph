import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_default_database_url_matches_the_documented_local_stack() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value() == (
        "postgresql+asyncpg://resumegraph:resumegraph-local-only@127.0.0.1:5432/resumegraph"
    )


def test_settings_load_prefixed_environment_variables(monkeypatch) -> None:
    database_url = "postgresql+asyncpg://env-user:env-password@database/env-database"
    monkeypatch.setenv("RESUMEGRAPH_ENVIRONMENT", "production")
    monkeypatch.setenv("RESUMEGRAPH_DATABASE_URL", database_url)
    monkeypatch.setenv("RESUMEGRAPH_READINESS_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("RESUMEGRAPH_COOKIE_SECURE", "true")
    monkeypatch.setenv("RESUMEGRAPH_ADMIN_SESSION_TTL_SECONDS", "3600")
    monkeypatch.setenv("RESUMEGRAPH_ADMIN_LOGIN_MAX_FAILURES", "4")
    monkeypatch.setenv("RESUMEGRAPH_ADMIN_LOGIN_WINDOW_SECONDS", "120")
    monkeypatch.setenv("RESUMEGRAPH_ACCESS_TOKEN_PEPPER", "production-pepper-value-for-tests-only")
    monkeypatch.setenv("RESUMEGRAPH_RECRUITER_SESSION_COOKIE_NAME", "recruiter_cookie")
    monkeypatch.setenv("RESUMEGRAPH_RECRUITER_SESSION_TTL_SECONDS", "1800")
    monkeypatch.setenv("RESUMEGRAPH_ACCESS_EXCHANGE_FAILURE_LIMIT", "8")
    monkeypatch.setenv("RESUMEGRAPH_ACCESS_EXCHANGE_FAILURE_WINDOW_SECONDS", "420")
    monkeypatch.setenv("RESUMEGRAPH_MARKDOWN_MAX_BYTES", "2097152")

    settings = Settings(_env_file=None)

    assert settings.environment == "production"
    assert settings.database_url.get_secret_value() == database_url
    assert settings.readiness_timeout_seconds == 2.5
    assert settings.cookie_secure is True
    assert settings.admin_session_ttl_seconds == 3600
    assert settings.admin_login_max_failures == 4
    assert settings.admin_login_window_seconds == 120
    assert settings.access_token_pepper.get_secret_value() == (
        "production-pepper-value-for-tests-only"
    )
    assert settings.recruiter_session_cookie_name == "recruiter_cookie"
    assert settings.recruiter_session_ttl_seconds == 1800
    assert settings.access_exchange_failure_limit == 8
    assert settings.access_exchange_failure_window_seconds == 420
    assert settings.markdown_max_bytes == 2 * 1024 * 1024
    assert database_url not in repr(settings)
    assert settings.access_token_pepper.get_secret_value() not in repr(settings)


def test_admin_auth_defaults_are_safe_for_local_development() -> None:
    settings = Settings(_env_file=None)

    assert settings.admin_session_cookie_name == "resumegraph_admin_session"
    assert settings.admin_session_ttl_seconds == 8 * 60 * 60
    assert settings.cookie_secure is False
    assert settings.admin_login_max_failures == 5
    assert settings.admin_login_window_seconds == 5 * 60
    assert settings.dependency_timeout_seconds == 3.0


def test_recruiter_access_defaults_are_separate_and_bounded() -> None:
    settings = Settings(_env_file=None)

    assert settings.access_token_pepper.get_secret_value() == (
        "local-development-access-token-pepper-change-me"
    )
    assert settings.recruiter_session_cookie_name == "resumegraph_recruiter_session"
    assert settings.recruiter_session_cookie_name != settings.admin_session_cookie_name
    assert settings.recruiter_session_ttl_seconds == 4 * 60 * 60
    assert settings.access_exchange_failure_limit == 10
    assert settings.access_exchange_failure_window_seconds == 10 * 60


def test_markdown_upload_limit_defaults_to_one_mibibyte() -> None:
    settings = Settings(_env_file=None)

    assert settings.markdown_max_bytes == 1024 * 1024


def test_markdown_upload_limit_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(markdown_max_bytes=0, _env_file=None)


def test_admin_and_recruiter_cookie_names_must_differ() -> None:
    with pytest.raises(ValidationError, match="cookie names must differ"):
        Settings(
            admin_session_cookie_name="same_cookie",
            recruiter_session_cookie_name="same_cookie",
            _env_file=None,
        )


def test_production_requires_secure_admin_cookie() -> None:
    with pytest.raises(ValidationError, match="COOKIE_SECURE must be true"):
        Settings(environment="production", cookie_secure=False, _env_file=None)
