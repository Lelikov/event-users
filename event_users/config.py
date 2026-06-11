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

    # External CRM
    is_sync_enabled: bool = False
    crm_api_url: str = Field(strict=True)
    crm_api_token: str = Field(strict=True)
    # AES-256 key as hex string (64 hex chars = 32 bytes)
    crm_encryption_key: str = Field(strict=True)

    @field_validator("crm_encryption_key")
    @classmethod
    def validate_encryption_key(cls, v: str) -> str:
        try:
            key_bytes = bytes.fromhex(v)
        except ValueError as err:
            raise ValueError("crm_encryption_key must be valid hex") from err
        if len(key_bytes) != 32:
            raise ValueError(f"crm_encryption_key must decode to 32 bytes (AES-256), got {len(key_bytes)}")
        return v

    crm_sync_interval_seconds: int = 300  # 5 minutes
    crm_sync_max_backoff_seconds: int = 1800  # cap for exponential backoff on repeated failures

    # event-admin cache invalidation
    event_admin_url: str = ""
    event_admin_cache_token: str = ""

    # RabbitMQ consumer (the events.user.email queue exists unconditionally,
    # so the consumer is on by default — otherwise messages accumulate forever)
    rabbit_url: str = "amqp://guest:guest@localhost:5672/"
    is_consumer_enabled: bool = True

    # CRM webhook
    crm_webhook_url: str = ""
    crm_webhook_token: str = ""
    is_webhook_enabled: bool = False
    webhook_poll_interval_seconds: int = 1
    webhook_batch_size: int = 10
    webhook_visibility_timeout_seconds: int = 120  # re-delivery window for claimed-but-unfinished rows


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Single process-wide Settings instance (also used by the DI container)."""
    return Settings()
