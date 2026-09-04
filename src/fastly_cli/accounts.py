"""Account value object and validation rules."""

from __future__ import annotations

import math
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://api.fastly.com"


class ConfigError(ValueError):
    """Raised when account configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class AccountConfig:
    """Credentials and endpoint settings for one Fastly account."""

    name: str
    token: str
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise ConfigError("account name must be a string")
        if not self.name.strip():
            raise ConfigError("account name cannot be empty")
        if not isinstance(self.token, str):
            raise ConfigError(f"account {self.name!r} token must be a string")
        if not self.token.strip():
            raise ConfigError(f"account {self.name!r} has an empty token")
        if not isinstance(self.base_url, str):
            raise ConfigError(f"account {self.name!r} has an invalid base_url")
        if isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)):
            raise ConfigError(f"account {self.name!r} timeout must be numeric")
        try:
            parsed = urlsplit(self.base_url)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as error:
            raise ConfigError(
                f"account {self.name!r} has an invalid base_url"
            ) from error
        if parsed.scheme not in {"http", "https"} or not hostname:
            raise ConfigError(f"account {self.name!r} has an invalid base_url")
        if port is not None and not 1 <= port <= 65535:
            raise ConfigError(f"account {self.name!r} has an invalid base_url")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigError(f"account {self.name!r} has an invalid base_url")
        try:
            finite_timeout = math.isfinite(self.timeout)
        except OverflowError:
            finite_timeout = False
        if not finite_timeout or self.timeout <= 0:
            raise ConfigError(f"account {self.name!r} timeout must be positive")
