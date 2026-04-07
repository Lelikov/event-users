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
    api_bearer_token: str = Field(default="dev-token", strict=True)

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

    crm_sync_interval_seconds: int = 10  # 5 minutes
