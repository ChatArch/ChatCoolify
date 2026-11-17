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


class PlatformConfig(BaseEnvConfig):
    """A user's endpoint and credentials; issued sessions live in TokenStore."""
    _title = 'ChatCoolify Platform'
    _aliases = ['coolify-platform']
    _storage_dir = 'CoolifyPlatform'
    CHATCOOLIFY_PLATFORM_URL = EnvField('CHATCOOLIFY_PLATFORM_URL',desc='HTTPS origin of the project platform')
    CHATCOOLIFY_PLATFORM_USERNAME = EnvField('CHATCOOLIFY_PLATFORM_USERNAME',desc='Invited platform account username')
    CHATCOOLIFY_PLATFORM_PASSWORD = EnvField('CHATCOOLIFY_PLATFORM_PASSWORD',is_sensitive=True,desc='Platform account password; opaque sessions remain in TokenStore')

    @classmethod
    def test(cls):
        from .platform_client import PlatformClient
        url=cls.CHATCOOLIFY_PLATFORM_URL.value
        if not url:
            print('Platform schema loaded; configure URL and account credentials to test sign-in.')
            return
        client=PlatformClient(url)
        username=cls.CHATCOOLIFY_PLATFORM_USERNAME.value
        password=cls.CHATCOOLIFY_PLATFORM_PASSWORD.value
        if not username or not password:
            raise RuntimeError('Configure platform username and password to test sign-in')
        client.login(username,password)
        try:
            client.request('/session')
        finally:
            client.request('/logout',method='POST',payload={})
        print('Platform account authentication passed; temporary test session revoked.')


class PlatformServerConfig(BaseEnvConfig):
    """Operator-only configuration, never returned by the public platform API."""
    _title = 'ChatCoolify Platform Server'
    _aliases = ['coolify-platform-server']
    _storage_dir = 'CoolifyPlatformServer'
    COOLIFY_BASE_URL = EnvField('COOLIFY_BASE_URL',desc='Existing native control origin')
    COOLIFY_API_TOKEN = EnvField('COOLIFY_API_TOKEN',is_sensitive=True,desc='Server-only native Team service token')
    CHATCOOLIFY_PLATFORM_DATA = EnvField('CHATCOOLIFY_PLATFORM_DATA',default='/data',desc='Persistent platform root')
    CHATCOOLIFY_CONTROL_URL = EnvField('CHATCOOLIFY_CONTROL_URL',desc='Public platform HTTPS origin')
    CHATCOOLIFY_DOMAIN_SUFFIX = EnvField('CHATCOOLIFY_DOMAIN_SUFFIX',desc='Operator-managed wildcard DNS suffix; defaults to the parent of platform.<suffix>')
    CHATCOOLIFY_RESERVED_HOSTS = EnvField('CHATCOOLIFY_RESERVED_HOSTS',desc='Comma-separated additional operator-reserved public hostnames outside native Team inventory')
    CHATCOOLIFY_INTERNAL_URL = EnvField('CHATCOOLIFY_INTERNAL_URL',desc='Private platform origin for frontend authorization')
    CHATCOOLIFY_SERVER_UUID = EnvField('CHATCOOLIFY_SERVER_UUID',desc='Operator-approved native server')
    CHATCOOLIFY_TEAM_ID = EnvField('CHATCOOLIFY_TEAM_ID',desc='Native service Team ID')
    CHATCOOLIFY_SOURCE_URL = EnvField('CHATCOOLIFY_SOURCE_URL',desc='Private read-only Git source base URL')
    CHATCOOLIFY_SOURCE_KEY_UUID = EnvField('CHATCOOLIFY_SOURCE_KEY_UUID',desc='Native key resource for restricted source clone')
    CHATCOOLIFY_EXTERNAL_TLS = EnvField('CHATCOOLIFY_EXTERNAL_TLS',default='false',desc='Existing external edge terminates HTTPS; native routing remains HTTP')
    CHATCOOLIFY_MAX_UPLOAD_BYTES = EnvField('CHATCOOLIFY_MAX_UPLOAD_BYTES',default='1073741824',desc='Maximum ZIP bytes, default 1 GiB; 0 means unlimited')
    CHATCOOLIFY_MAX_EXPANDED_BYTES = EnvField('CHATCOOLIFY_MAX_EXPANDED_BYTES',default='0',desc='Maximum expanded artifact bytes; 0 means unlimited')
    CHATCOOLIFY_MAX_ARTIFACT_FILES = EnvField('CHATCOOLIFY_MAX_ARTIFACT_FILES',default='0',desc='Maximum archive file/directory entries; 0 means unlimited')

    @classmethod
    def test(cls):
        from .platform_artifact import ArtifactLimits
        ArtifactLimits.from_values({name:getattr(cls,name).value for name in (
            'CHATCOOLIFY_MAX_UPLOAD_BYTES','CHATCOOLIFY_MAX_EXPANDED_BYTES','CHATCOOLIFY_MAX_ARTIFACT_FILES')})
        print('Platform server artifact policy valid; credentials stay server-side.')


__all__ = ["CoolifyConfig", "PlatformConfig", "PlatformServerConfig"]
