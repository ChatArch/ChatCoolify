"""Typed, fail-closed client for the official Coolify REST API."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://coolify.example.com"


class CoolifyError(RuntimeError):
    """Base exception for ChatCoolify."""


class CoolifyConfigurationError(CoolifyError):
    """Raised when the client lacks required local configuration."""


class CoolifyPermissionError(CoolifyError):
    """Raised before a write request when explicit consent is missing."""


class CoolifyAPIError(CoolifyError):
    """A sanitized error response from the Coolify API."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(f"Coolify API returned HTTP {status}: {message}")


@dataclass(frozen=True)
class PublicApplicationSpec:
    """Minimum safe payload for a public Git-based Coolify application."""

    project_uuid: str
    server_uuid: str
    environment_name: str
    environment_uuid: str
    git_repository: str
    git_branch: str = "main"
    build_pack: str = "static"
    name: str | None = None
    domains: str | None = None
    publish_directory: str | None = None
    is_static: bool = True
    is_spa: bool = True
    port: int | None = None
    health_check_path: str | None = None

    def as_payload(self, *, instant_deploy: bool = False) -> dict[str, Any]:
        """Return the official API payload without adding sensitive fields."""

        _require_text("project_uuid", self.project_uuid)
        _require_text("server_uuid", self.server_uuid)
        _require_text("environment_name", self.environment_name)
        _require_text("environment_uuid", self.environment_uuid)
        _require_repository(self.git_repository)
        _require_text("git_branch", self.git_branch)
        _require_text("build_pack", self.build_pack)

        payload: dict[str, Any] = {
            "project_uuid": self.project_uuid,
            "server_uuid": self.server_uuid,
            "environment_name": self.environment_name,
            "environment_uuid": self.environment_uuid,
            "git_repository": self.git_repository,
            "git_branch": self.git_branch,
            "build_pack": self.build_pack,
            "is_static": self.is_static,
            "is_spa": self.is_spa,
            "instant_deploy": instant_deploy,
        }
        optional_text = {
            "name": self.name,
            "domains": self.domains,
            "publish_directory": self.publish_directory,
            "health_check_path": self.health_check_path,
        }
        for key, value in optional_text.items():
            if value is not None and value.strip():
                payload[key] = value.strip()
        if self.port is not None:
            if not 1 <= self.port <= 65535:
                raise CoolifyConfigurationError("port must be between 1 and 65535")
            payload["ports_exposes"] = str(self.port)
        return payload


class CoolifyClient:
    """Small client around documented Coolify REST endpoints.

    Instances are read-only by default. Callers must opt in to writes with
    ``allow_write=True`` and use a Coolify token that itself has write or deploy
    permission. This creates a local safety gate in addition to Coolify's own
    team scope and API-token permissions.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        token: str | None = None,
        allow_write: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = _normalise_base_url(base_url)
        self.token = token.strip() if token else None
        self.allow_write = allow_write
        self.timeout = timeout

    @classmethod
    def from_env(cls, *, allow_write: bool = False) -> "CoolifyClient":
        """Create a client from process environment or the active ChatEnv profile."""

        profile_values = _load_chatenv_values()
        return cls(
            os.getenv("COOLIFY_BASE_URL") or profile_values.get("COOLIFY_BASE_URL") or DEFAULT_BASE_URL,
            token=os.getenv("COOLIFY_API_TOKEN") or profile_values.get("COOLIFY_API_TOKEN"),
            allow_write=allow_write,
        )

    def health(self) -> dict[str, Any]:
        """Read the public health endpoint without an API token."""

        result = self._request("GET", "/api/health", auth=False)
        if isinstance(result, dict):
            return result
        return {"ok": str(result).strip().upper() == "OK", "response": str(result).strip()}

    def current_team(self) -> Mapping[str, Any]:
        return _as_mapping(self._request("GET", "/api/v1/team"), "current team")

    def list_teams(self) -> Sequence[Mapping[str, Any]]:
        return _as_sequence(self._request("GET", "/api/v1/teams"), "teams")

    def list_projects(self) -> Sequence[Mapping[str, Any]]:
        return _as_sequence(self._request("GET", "/api/v1/projects"), "projects")

    def list_applications(self) -> Sequence[Mapping[str, Any]]:
        return _as_sequence(self._request("GET", "/api/v1/applications"), "applications")

    def list_servers(self) -> Sequence[Mapping[str, Any]]:
        return _as_sequence(self._request("GET", "/api/v1/servers"), "servers")

    def list_deployments(self, application_uuid: str, *, skip: int = 0, take: int = 20) -> Sequence[Mapping[str, Any]]:
        _require_text("application_uuid", application_uuid)
        if skip < 0 or take < 1:
            raise CoolifyConfigurationError("skip must be >= 0 and take must be >= 1")
        query = urlencode({"skip": skip, "take": take})
        path = f"/api/v1/deployments/applications/{quote(application_uuid, safe='')}?{query}"
        return _as_sequence(self._request("GET", path), "deployments")

    def create_project(self, name: str, *, description: str | None = None) -> Mapping[str, Any]:
        """Create a project only after the caller explicitly enabled writes."""

        _require_text("name", name)
        payload: dict[str, Any] = {"name": name.strip()}
        if description and description.strip():
            payload["description"] = description.strip()
        return _as_mapping(self._request("POST", "/api/v1/projects", payload=payload, write=True), "project")

    def create_public_application(
        self,
        spec: PublicApplicationSpec,
        *,
        instant_deploy: bool = False,
    ) -> Mapping[str, Any]:
        """Create a public Git application using Coolify's documented API."""

        return _as_mapping(
            self._request(
                "POST",
                "/api/v1/applications/public",
                payload=spec.as_payload(instant_deploy=instant_deploy),
                write=True,
            ),
            "application",
        )

    def deploy(self, application_uuid: str, *, force: bool = False) -> Mapping[str, Any]:
        """Trigger an application deployment with an explicit deploy-capable client."""

        _require_text("application_uuid", application_uuid)
        return _as_mapping(
            self._request(
                "POST",
                "/api/v1/deploy",
                payload={"uuid": application_uuid, "force": force},
                write=True,
            ),
            "deployment",
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        auth: bool = True,
        write: bool = False,
    ) -> Any:
        if write and not self.allow_write:
            raise CoolifyPermissionError(
                "write operation blocked locally; recreate the client or CLI with explicit write permission"
            )
        if auth and not self.token:
            raise CoolifyConfigurationError(
                "COOLIFY_API_TOKEN is required for protected Coolify API operations"
            )

        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        headers = {"Accept": "application/json", "User-Agent": "ChatCoolify/0.1.0"}
        data = None
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")

        request = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=self.timeout) as response:  # nosec B310 - URL is user-configured API origin
                content_type = response.headers.get_content_type()
                raw = response.read().decode("utf-8")
                if not raw:
                    return None
                if content_type == "application/json" or raw.lstrip().startswith(("{", "[")):
                    return json.loads(raw)
                return raw
        except HTTPError as error:
            message = _error_message(error)
            raise CoolifyAPIError(error.code, message) from error
        except URLError as error:
            raise CoolifyError(f"Coolify API is unreachable: {error.reason}") from error


def _load_chatenv_values() -> Mapping[str, str]:
    """Read the active package-owned ChatEnv profile without copying secrets."""

    try:
        from chatenv import EnvStore, get_paths

        from .config import CoolifyConfig

        return EnvStore(get_paths().envs_dir).load_active(CoolifyConfig)
    except (ImportError, OSError, ValueError):
        return {}


def _normalise_base_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CoolifyConfigurationError("COOLIFY_BASE_URL must be an absolute http(s) URL")
    return candidate


def _require_text(name: str, value: str) -> None:
    if not value or not value.strip():
        raise CoolifyConfigurationError(f"{name} is required")


def _require_repository(value: str) -> None:
    _require_text("git_repository", value)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise CoolifyConfigurationError("git_repository must be an HTTPS repository URL")


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CoolifyError(f"Coolify returned an unexpected {label} response")
    return value


def _as_sequence(value: Any, label: str) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise CoolifyError(f"Coolify returned an unexpected {label} response")
    return value


def _error_message(error: HTTPError) -> str:
    """Extract only a short server message; never include request headers or token data."""

    try:
        raw = error.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        if isinstance(parsed, Mapping) and isinstance(parsed.get("message"), str):
            return parsed["message"][:500]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return error.reason or "request failed"


__all__ = [
    "DEFAULT_BASE_URL",
    "CoolifyAPIError",
    "CoolifyClient",
    "CoolifyConfigurationError",
    "CoolifyError",
    "CoolifyPermissionError",
    "PublicApplicationSpec",
]
