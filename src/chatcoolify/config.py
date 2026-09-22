"""ChatEnv schema for ChatCoolify credentials and API endpoint."""

from __future__ import annotations

import os

from chatenv import BaseEnvConfig, EnvField, EnvStore, get_paths


class CoolifyConfig(BaseEnvConfig):
    """Typed configuration for the existing Coolify control plane."""

    _title = "Coolify Configuration"
    _aliases = ["coolify", "chatcoolify"]
    _storage_dir = "Coolify"

    COOLIFY_BASE_URL = EnvField(
        "COOLIFY_BASE_URL",
        default="https://coolify.example.com",
        desc="Public HTTPS URL of the Coolify control plane",
    )
    COOLIFY_API_TOKEN = EnvField(
        "COOLIFY_API_TOKEN",
        desc="Team-scoped Coolify API token; use the minimum required permissions and expiration",
        is_sensitive=True,
    )

    @classmethod
    def test(cls) -> None:
        """Validate a configured endpoint, while keeping unconfigured schemas offline."""

        from .client import DEFAULT_BASE_URL, CoolifyClient, CoolifyError

        profile_values = EnvStore(get_paths().envs_dir).load_active(cls)
        base_url = os.getenv("COOLIFY_BASE_URL") or profile_values.get("COOLIFY_BASE_URL") or DEFAULT_BASE_URL
        if base_url == DEFAULT_BASE_URL:
            print("ChatCoolify schema loaded; configure COOLIFY_BASE_URL to run a health check.")
            return
        try:
            result = CoolifyClient(base_url).health()
        except CoolifyError as error:
            raise RuntimeError(f"Coolify health check failed: {error}") from error
        if not result.get("ok"):
            raise RuntimeError("Coolify health check did not report OK")
        print(f"Coolify health check passed for {base_url}.")


__all__ = ["CoolifyConfig"]
