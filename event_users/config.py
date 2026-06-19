from functools import lru_cache

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    debug: bool = False
    log_level: str = "INFO"
    jwt_secret_key: str = Field(...)
    jwt_algorithm: str = "HS256"
    # Optional audience/issuer binding. When set, JWTs MUST carry matching
    # aud/iss claims (tokens minted by event-admin). Left unset they are not
    # verified, which keeps rollout backward-compatible.
    jwt_audience: str | None = None
    jwt_issuer: str | None = None
    api_bearer_token: str | None = None
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid_levels:
            raise ValueError(
                f"Invalid log_level: {v!r}. Must be one of {sorted(valid_levels)}",
            )
        return upper

    postgres_dsn: PostgresDsn = Field(strict=True)

    # event-admin cache invalidation
    event_admin_url: str = ""
    event_admin_cache_token: str = ""

    # RabbitMQ consumer (the events.user.email queue exists unconditionally,
    # so the consumer is on by default — otherwise messages accumulate forever)
    rabbit_url: str = "amqp://guest:guest@localhost:5672/"
    is_consumer_enabled: bool = True
    rabbit_publish_timeout: float = 10.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Single process-wide Settings instance (also used by the DI container)."""
    return Settings()
