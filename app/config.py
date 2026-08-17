from functools import lru_cache
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "production"
    log_level: str = "INFO"
    database_url: str = "sqlite:////data/gateway.db"
    public_base_url: str = "http://localhost:8090"
    allowed_origins: str = "http://localhost:8090"
    telegram_bot_username: str = "replace_me"
    telegram_bot_token: str = "replace_me"
    telegram_webhook_secret: str = "replace_me"
    link_token_ttl_seconds: int = 600
    webhook_max_body_bytes: int = 1_048_576
    event_retention_days: int = 30
    zammad_base_url: str = "http://localhost:3000"
    zammad_verify_tls: bool = True
    zammad_request_timeout_seconds: float = 10.0
    zammad_api_token: str = "replace_me"
    zammad_webhook_secret: str = "replace_me"
    zammad_service_user_id: int = 0
    zammad_admin_role_id: int = 1
    zammad_agent_role_id: int = 2
    zammad_customer_role_id: int = 3

    @field_validator("public_base_url", "zammad_base_url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        value = value.rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an absolute HTTP(S) URL")
        return value

    @field_validator("telegram_bot_username")
    @classmethod
    def normalize_bot_username(cls, value: str) -> str:
        value = value.strip().lstrip("@")
        if not value:
            raise ValueError("must not be empty")
        return value

    @property
    def origin_allowlist(self) -> set[str]:
        return {item.strip().rstrip("/") for item in self.allowed_origins.split(",") if item.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
