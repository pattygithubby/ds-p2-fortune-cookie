"""All settings for the website, read from the environment in one place.

The election itself is configured by the BULLY_* variables, which are read by
bully.__main__.Config (see src/bully/__main__.py) and are not repeated here.
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Settings for the web side of one pod."""

    web_port: int = 8080
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Config":
        """Build a Config from environment variables. Raises ValueError if a value is wrong."""
        try:
            web_port = int(env.get("WEB_PORT", cls.web_port))
        except ValueError:
            raise ValueError(f"WEB_PORT must be a number, not {env['WEB_PORT']!r}") from None
        return cls(
            web_port=web_port,
            log_level=env.get("LOG_LEVEL", cls.log_level).upper(),
        )
