from pathlib import Path

import yaml


def _compose() -> dict[str, object]:
    return yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))


def test_compose_defines_host_only_frontend_behind_healthy_backend() -> None:
    services = _compose()["services"]

    frontend = services["frontend"]
    assert frontend["build"] == {"context": "./frontend"}
    assert frontend["ports"] == ["127.0.0.1:${FRONTEND_PORT:-5173}:80"]
    assert frontend["depends_on"] == {
        "backend": {"condition": "service_healthy"},
    }
    assert "healthcheck" in services["backend"]


def test_frontend_container_serves_spa_and_proxies_same_origin_api() -> None:
    dockerfile = Path("frontend/Dockerfile").read_text(encoding="utf-8")
    nginx = Path("frontend/nginx.conf").read_text(encoding="utf-8")

    assert "npm run build" in dockerfile
    assert "COPY --from=build /app/dist /usr/share/nginx/html" in dockerfile
    assert "try_files $uri $uri/ /index.html" in nginx
    assert "proxy_pass http://backend:8000" in nginx


def test_backend_compose_exposes_all_phase_4_finite_budget_settings() -> None:
    backend_environment = _compose()["services"]["backend"]["environment"]

    expected = {
        "RESUMEGRAPH_AGENT_SUPERVISOR_MAX_SPECIALIST_CALLS",
        "RESUMEGRAPH_AGENT_PROFILE_MAX_TOOL_CALLS",
        "RESUMEGRAPH_AGENT_PROJECT_MAX_TOOL_CALLS",
        "RESUMEGRAPH_AGENT_TECHNICAL_MAX_TOOL_CALLS",
        "RESUMEGRAPH_AGENT_VERIFICATION_MAX_RUNS",
        "RESUMEGRAPH_AGENT_MAX_ANSWER_REPAIRS",
        "RESUMEGRAPH_AGENT_MAX_GRAPH_STEPS",
        "RESUMEGRAPH_AGENT_RUN_TIMEOUT_SECONDS",
        "RESUMEGRAPH_CONVERSATION_MAX_TURNS",
        "RESUMEGRAPH_CONVERSATION_TTL_SECONDS",
        "RESUMEGRAPH_CONVERSATION_SUMMARY_MAX_CHARACTERS",
    }

    assert expected <= set(backend_environment)
