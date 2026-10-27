"""ChatCoolify: AI-safe integration with the official Coolify API."""

from .client import (
    DEFAULT_BASE_URL,
    CoolifyAPIError,
    CoolifyClient,
    CoolifyConfigurationError,
    CoolifyError,
    CoolifyPermissionError,
    PublicApplicationSpec,
)

__version__ = "0.2.4"

from .platform import PlatformService
from .platform_client import PlatformClient
from .platform_artifact import PlatformError
from .platform_backend import CoolifyBackend

__all__ = [
    "DEFAULT_BASE_URL",
    "CoolifyAPIError",
    "CoolifyClient",
    "CoolifyConfigurationError",
    "CoolifyError",
    "CoolifyPermissionError",
    "PublicApplicationSpec",
    "PlatformService",
    "PlatformClient",
    "PlatformError",
    "CoolifyBackend",
    "__version__",
]
