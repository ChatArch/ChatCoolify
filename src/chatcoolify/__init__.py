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

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_BASE_URL",
    "CoolifyAPIError",
    "CoolifyClient",
    "CoolifyConfigurationError",
    "CoolifyError",
    "CoolifyPermissionError",
    "PublicApplicationSpec",
    "__version__",
]
