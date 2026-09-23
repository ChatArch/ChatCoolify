from __future__ import annotations

from contextlib import contextmanager
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any, Iterator
from urllib.error import URLError

import pytest

from chatcoolify import (
    CoolifyAPIError,
    CoolifyClient,
    CoolifyConfigurationError,
    CoolifyError,
    CoolifyPermissionError,
    PublicApplicationSpec,
)


@contextmanager
def fake_coolify() -> Iterator[dict[str, Any]]:
    state: dict[str, Any] = {"requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _record(self, payload: Any | None = None) -> None:
            state["requests"].append(
                {
                    "method": self.command,
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "payload": payload,
                }
            )

        def do_GET(self) -> None:  # noqa: N802
            self._record()
            if self.path == "/api/health":
                body = b"OK"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/api/v1/team":
                self._json(200, {"id": 1, "name": "demo-team"})
                return
            if self.path == "/api/v1/projects/project-1":
                self._json(
                    200,
                    {
                        "uuid": "project-1",
                        "name": "demo",
                        "team": {"name": "demo-team", "private_value": "do-not-expose"},
                        "environments": [
                            {
                                "uuid": "environment-1",
                                "name": "production",
                                "description": None,
                                "project": {"private_value": "do-not-expose"},
                            }
                        ],
                    },
                )
                return
            if self.path == "/api/v1/projects":
                self._json(200, [{"uuid": "project-1", "name": "demo"}])
                return
            if self.path == "/api/v1/applications/app-1":
                self._json(
                    200,
                    {
                        "uuid": "app-1",
                        "name": "demo-site",
                        "fqdn": "https://app-1.example.com",
                        "status": "running:healthy",
                        "destination": {"server": {"proxy": {"configuration": "do-not-expose"}}},
                        "manual_webhook_secret_github": "do-not-expose",
                    },
                )
                return
            if self.path == "/api/v1/applications":
                self._json(200, [])
                return
            if self.path == "/api/v1/servers":
                self._json(200, [{"uuid": "server-1", "name": "worker"}])
                return
            if self.path.startswith("/api/v1/deployments/applications/"):
                self._json(200, {"count": 1, "deployments": [{"deployment_uuid": "deploy-1", "status": "finished"}]})
                return
            if self.path == "/api/v1/reflected-token":
                self._json(400, {"message": f"Rejected Bearer {self.headers.get('Authorization')}"})
                return
            self._json(404, {"message": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._record(payload)
            if self.path == "/api/v1/projects":
                self._json(201, {"uuid": "project-2", **payload})
                return
            if self.path == "/api/v1/applications/public":
                self._json(201, {"uuid": "app-1", **payload})
                return
            if self.path == "/api/v1/deploy":
                self._json(200, {"deployments": [{"deployment_uuid": "deploy-1"}], **payload})
                return
            self._json(404, {"message": "not found"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["base_url"] = f"http://127.0.0.1:{server.server_port}"
    try:
        yield state
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_health_does_not_require_a_token() -> None:
    with fake_coolify() as fake:
        result = CoolifyClient(fake["base_url"]).health()
    assert result == {"ok": True, "response": "OK"}
    assert fake["requests"][0]["authorization"] is None


def test_inventory_sends_team_scoped_bearer_token() -> None:
    with fake_coolify() as fake:
        client = CoolifyClient(fake["base_url"], token="42|test-token")
        assert client.current_team()["name"] == "demo-team"
        assert client.list_projects()[0]["uuid"] == "project-1"
    assert all(request["authorization"] == "Bearer 42|test-token" for request in fake["requests"])


def test_project_detail_and_deployment_envelope_are_supported() -> None:
    with fake_coolify() as fake:
        client = CoolifyClient(fake["base_url"], token="42|test-token")
        project = client.get_project("project-1")
        application = client.get_application("app-1")
        deployments = client.list_deployments("application-1")
    assert project["environments"][0]["uuid"] == "environment-1"
    assert "team" not in project
    assert "project" not in project["environments"][0]
    assert application["fqdn"] == "https://app-1.example.com"
    assert application["status"] == "running:healthy"
    assert "destination" not in application
    assert "manual_webhook_secret_github" not in application
    assert deployments == [{"deployment_uuid": "deploy-1", "status": "finished"}]


def test_from_env_uses_active_profile_when_process_env_is_absent(monkeypatch) -> None:
    monkeypatch.delenv("COOLIFY_BASE_URL", raising=False)
    monkeypatch.delenv("COOLIFY_API_TOKEN", raising=False)
    monkeypatch.setattr(
        "chatcoolify.client._load_chatenv_values",
        lambda: {"COOLIFY_BASE_URL": "https://profile.example.com", "COOLIFY_API_TOKEN": "7|profile-token"},
    )
    client = CoolifyClient.from_env()
    assert client.base_url == "https://profile.example.com"
    assert client.token == "7|profile-token"


def test_process_environment_overrides_active_profile(monkeypatch) -> None:
    monkeypatch.setenv("COOLIFY_BASE_URL", "https://process.example.com")
    monkeypatch.setenv("COOLIFY_API_TOKEN", "8|process-token")
    monkeypatch.setattr(
        "chatcoolify.client._load_chatenv_values",
        lambda: {"COOLIFY_BASE_URL": "https://profile.example.com", "COOLIFY_API_TOKEN": "7|profile-token"},
    )
    client = CoolifyClient.from_env()
    assert client.base_url == "https://process.example.com"
    assert client.token == "8|process-token"


def test_writes_fail_closed_before_any_request() -> None:
    with fake_coolify() as fake:
        client = CoolifyClient(fake["base_url"], token="42|test-token")
        with pytest.raises(CoolifyPermissionError):
            client.create_project("should-not-exist")
    assert fake["requests"] == []


def test_create_project_uses_explicit_write_mode() -> None:
    with fake_coolify() as fake:
        client = CoolifyClient(fake["base_url"], token="42|test-token", allow_write=True)
        result = client.create_project("demo", description="safe test")
    assert result["uuid"] == "project-2"
    assert fake["requests"][-1]["payload"] == {"name": "demo", "description": "safe test"}


def test_public_application_payload_is_typed_and_static() -> None:
    with fake_coolify() as fake:
        spec = PublicApplicationSpec(
            project_uuid="project-1",
            server_uuid="server-1",
            environment_name="production",
            environment_uuid="environment-1",
            git_repository="https://github.com/example/site",
            domains="https://demo.example.com",
            publish_directory="dist",
        )
        client = CoolifyClient(fake["base_url"], token="42|test-token", allow_write=True)
        result = client.create_public_application(spec)
    assert result["uuid"] == "app-1"
    payload = fake["requests"][-1]["payload"]
    assert payload["build_pack"] == "static"
    assert payload["is_static"] is True
    assert payload["instant_deploy"] is False
    assert payload["domains"] == "https://demo.example.com"
    assert payload["autogenerate_domain"] is False


def test_public_application_without_domain_requests_wildcard_allocation() -> None:
    spec = PublicApplicationSpec(
        project_uuid="project-1",
        server_uuid="server-1",
        environment_name="production",
        environment_uuid="environment-1",
        git_repository="https://github.com/example/site",
        health_check_path="/health",
    )
    payload = spec.as_payload()
    assert "domains" not in payload
    assert payload["autogenerate_domain"] is True
    assert payload["health_check_enabled"] is True
    assert payload["health_check_path"] == "/health"


def test_invalid_repository_is_rejected_locally() -> None:
    spec = PublicApplicationSpec(
        project_uuid="project-1",
        server_uuid="server-1",
        environment_name="production",
        environment_uuid="environment-1",
        git_repository="git@github.com:example/site.git",
    )
    with pytest.raises(Exception, match="HTTPS repository"):
        spec.as_payload()


def test_api_error_does_not_expose_request_headers() -> None:
    with fake_coolify() as fake:
        client = CoolifyClient(fake["base_url"], token="42|test-token")
        with pytest.raises(CoolifyAPIError) as error:
            client._request("GET", "/api/v1/missing")
    assert "not found" in str(error.value)
    assert "test-token" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_reflected_token_is_redacted_from_api_error() -> None:
    with fake_coolify() as fake:
        client = CoolifyClient(fake["base_url"], token="42|test-token")
        with pytest.raises(CoolifyAPIError) as error:
            client._request("GET", "/api/v1/reflected-token")
    assert "test-token" not in str(error.value)
    assert "[REDACTED]" in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_network_error_redacts_token_without_retaining_context(monkeypatch) -> None:
    def fail_request(*_args: object, **_kwargs: object) -> None:
        raise URLError("Bearer 42|test-token")

    monkeypatch.setattr("chatcoolify.client.urlopen", fail_request)
    client = CoolifyClient("https://api.example.com", token="42|test-token")
    with pytest.raises(CoolifyError) as error:
        client.current_team()
    assert "test-token" not in str(error.value)
    assert "[REDACTED]" in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_base_url_rejects_embedded_credentials() -> None:
    with pytest.raises(CoolifyConfigurationError, match="must not include credentials") as error:
        CoolifyClient("https://user:secret@example.com")
    assert "secret" not in str(error.value)
