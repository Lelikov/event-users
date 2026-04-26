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

    # event-admin cache invalidation
    event_admin_url: str = ""
    event_admin_cache_token: str = ""

    # RabbitMQ consumer
    rabbit_url: str = "amqp://guest:guest@localhost:5672/"
    is_consumer_enabled: bool = False
