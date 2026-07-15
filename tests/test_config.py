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
    monkeypatch.setenv("RESUMEGRAPH_CHUNK_MAX_CHARACTERS", "2400")

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
    assert settings.chunk_max_characters == 2400
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


def test_chunk_size_defaults_to_two_thousand_characters_and_must_be_positive() -> None:
    settings = Settings(_env_file=None)

    assert settings.chunk_max_characters == 2_000
    with pytest.raises(ValidationError):
        Settings(chunk_max_characters=0, _env_file=None)


def test_quality_provider_defaults_are_bounded_and_thinking_is_disabled() -> None:
    settings = Settings(_env_file=None)

    assert settings.deepseek_api_key.get_secret_value() == ""
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.deepseek_quality_model == "deepseek-v4-pro"
    assert settings.deepseek_quality_thinking_enabled is False
    assert settings.quality_judge_timeout_seconds == 45
    assert settings.quality_judge_max_retries == 2
    assert settings.quality_judge_batch_size == 5


def test_quality_provider_loads_prefixed_environment_without_exposing_key(monkeypatch) -> None:
    key = "fictional-deepseek-key-for-settings-test"
    monkeypatch.setenv("RESUMEGRAPH_DEEPSEEK_API_KEY", key)
    monkeypatch.setenv("RESUMEGRAPH_DEEPSEEK_QUALITY_THINKING_ENABLED", "true")
    monkeypatch.setenv("RESUMEGRAPH_QUALITY_JUDGE_BATCH_SIZE", "8")

    settings = Settings(_env_file=None)

    assert settings.deepseek_api_key.get_secret_value() == key
    assert settings.deepseek_quality_thinking_enabled is True
    assert settings.quality_judge_batch_size == 8
    assert key not in repr(settings)


def test_embedding_defaults_match_the_confirmed_openai_compatible_configuration() -> None:
    settings = Settings(_env_file=None)

    assert settings.embedding_provider_name == "zhipu"
    assert settings.embedding_base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert settings.embedding_api_key.get_secret_value() == ""
    assert settings.embedding_model == "embedding-3"
    assert settings.embedding_dimensions == 1024
    assert settings.embedding_send_dimensions is True
    assert settings.embedding_batch_size == 10
    assert settings.embedding_timeout_seconds == 30
    assert settings.embedding_max_retries == 2


def test_single_turn_rag_defaults_are_bounded_and_reuse_deepseek_configuration() -> None:
    settings = Settings(_env_file=None)

    assert settings.rag_top_k == 6
    assert settings.rag_max_context_characters == 12_000
    assert settings.rag_answer_timeout_seconds == 45
    assert settings.rag_answer_output_retries == 1
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.deepseek_quality_model == "deepseek-v4-pro"


def test_embedding_configuration_loads_unprefixed_environment_and_masks_key(monkeypatch) -> None:
    key = "fictional-openai-compatible-embedding-key"
    monkeypatch.setenv("EMBEDDING_PROVIDER_NAME", "custom-provider")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://custom.example/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", key)
    monkeypatch.setenv("EMBEDDING_MODEL", "custom-embedding")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "512")
    monkeypatch.setenv("EMBEDDING_SEND_DIMENSIONS", "false")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "12")
    monkeypatch.setenv("EMBEDDING_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("EMBEDDING_MAX_RETRIES", "1")

    settings = Settings(_env_file=None)

    assert settings.embedding_provider_name == "custom-provider"
    assert settings.embedding_base_url == "https://custom.example/v1"
    assert settings.embedding_api_key.get_secret_value() == key
    assert settings.embedding_model == "custom-embedding"
    assert settings.embedding_dimensions == 512
    assert settings.embedding_send_dimensions is False
    assert settings.embedding_batch_size == 12
    assert settings.embedding_timeout_seconds == 20
    assert settings.embedding_max_retries == 1
    assert key not in repr(settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quality_judge_timeout_seconds", 0),
        ("quality_judge_max_retries", 5),
        ("quality_judge_batch_size", 0),
        ("quality_rule_min_characters", -1),
        ("quality_rule_abnormal_character_ratio", 1.1),
        ("embedding_dimensions", 0),
        ("embedding_batch_size", 0),
        ("embedding_timeout_seconds", 0),
        ("embedding_max_retries", 5),
        ("rag_top_k", 0),
        ("rag_max_context_characters", 0),
        ("rag_answer_timeout_seconds", 0),
        ("rag_answer_output_retries", 2),
    ],
)
def test_quality_provider_and_rule_bounds_are_validated(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value}, _env_file=None)


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
