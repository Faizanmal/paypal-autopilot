"""Application configuration.

All configuration is read from environment variables (optionally via a
local `.env` file during development — see `.env.example` at the repo
root). No credential or secret ever has a non-empty default here.

Sandbox enforcement (project rule: "Sandbox is the only enabled mode for
the hackathon") is implemented as a hard startup validation: `PAYPAL_ENV`
must be `sandbox` unless `ALLOW_LIVE_PAYPAL` is explicitly `true`, and
nothing in this codebase currently sets that flag.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path, PurePath
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _environment_file(config_path: PurePath) -> PurePath:
    api_root = config_path.parent.parent.parent
    if api_root.name == "api" and api_root.parent.name == "apps":
        return api_root.parent.parent / ".env"
    # Docker copies the API to /app, without the enclosing monorepo directories.
    return api_root / ".env"


_REPO_ENV = _environment_file(Path(__file__).resolve())


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class AIProviderName(StrEnum):
    AUTO = "auto"
    GROQ = "groq"
    GEMINI = "gemini"
    OPENAI = "openai"
    FALLBACK_RULES = "fallback_rules"


class PayPalEnv(StrEnum):
    SANDBOX = "sandbox"
    LIVE = "live"


PAYPAL_BASE_URLS: dict[PayPalEnv, str] = {
    PayPalEnv.SANDBOX: "https://api-m.sandbox.paypal.com",
    PayPalEnv.LIVE: "https://api-m.paypal.com",
}

# MVP only supports 2-decimal currencies. Zero/three-decimal currencies
# (e.g. JPY, BHD) are explicitly out of scope.
SUPPORTED_CURRENCIES: frozenset[str] = frozenset({"USD"})
MONEY_DECIMAL_PLACES: int = 2
MONEY_QUANTIZE = Decimal(10) ** -MONEY_DECIMAL_PLACES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ENV), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: AppEnv = AppEnv.DEVELOPMENT
    secret_key: SecretStr = Field(default=SecretStr(""))

    # No fallback connection string. A hardcoded user, password, or database
    # name here would ignore .env and fail authentication against the real role.
    database_url: str
    database_url_sync: str

    redis_url: str = "redis://localhost:6380/0"

    paypal_env: PayPalEnv = PayPalEnv.SANDBOX
    paypal_client_id: str = ""
    paypal_client_secret: SecretStr = Field(default=SecretStr(""))
    paypal_webhook_id: str = ""
    paypal_api_base_url: str = ""
    paypal_sandbox_business_email: str = ""
    paypal_sandbox_buyer_email: str = ""
    # Execution also requires the OAuth token to include the Payouts scope.
    # Diagnostics never turn this on and never create a payout.
    paypal_payouts_execution: bool = False
    allow_live_paypal: bool = False

    # auto = groq → gemini → openai → rule-based fallback (keys that are set).
    ai_provider: AIProviderName = AIProviderName.AUTO
    groq_api_key: SecretStr = Field(default=SecretStr(""))
    gemini_api_key: SecretStr = Field(default=SecretStr(""))
    openai_api_key: SecretStr = Field(default=SecretStr(""))
    studio_ai_model: str = "gpt-4o-mini"
    render_api_key: SecretStr = Field(default=SecretStr(""))
    render_report_task: str = ""
    render_use_local_dev: bool = False
    render_local_dev_url: str = ""

    next_public_api_base_url: str = "http://localhost:8000"
    # Comma-separated browser origins allowed to call the API with cookies.
    # Required when APP_ENV=production (e.g. https://app.example.com).
    # Environment variable: CORS_ORIGINS
    cors_origins: str = ""
    # Public HTTPS origin of this API, used in deployment docs / webhook tips.
    public_api_base_url: str = ""

    @field_validator("database_url", "database_url_sync", mode="before")
    @classmethod
    def _database_driver_url(cls, value: str, info: ValidationInfo) -> str:
        # Managed hosts provide ordinary Postgres URLs for both async and sync clients.
        # Explicit driver URLs used in local development remain unchanged.
        if value.startswith(("postgres://", "postgresql://")):
            driver = "asyncpg" if info.field_name == "database_url" else "psycopg"
            return f"postgresql+{driver}://{value.split('://', 1)[1]}"
        return value

    @model_validator(mode="after")
    def _enforce_sandbox_only(self) -> Settings:
        secret = self.secret_key.get_secret_value().strip()
        if not secret:
            raise ValueError("SECRET_KEY must be set to a non-empty value.")
        if len(secret) < 16:
            raise ValueError("SECRET_KEY must be at least 16 characters.")
        if self.paypal_env is PayPalEnv.LIVE and not self.allow_live_paypal:
            raise ValueError(
                "PAYPAL_ENV=live requires ALLOW_LIVE_PAYPAL=true to be set "
                "explicitly. This project is sandbox-only by default; see "
                "docs/SECURITY.md section 10."
            )
        override = self.paypal_api_base_url.strip()
        if override:
            parsed = urlsplit(override)
            host = (parsed.hostname or "").lower()
            allowed_hosts = (
                {"api-m.sandbox.paypal.com", "api.sandbox.paypal.com"}
                if self.paypal_env is PayPalEnv.SANDBOX
                else {"api-m.paypal.com", "api.paypal.com"}
            )
            if (
                parsed.scheme != "https"
                or host not in allowed_hosts
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in (None, 443)
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "PAYPAL_API_BASE_URL must be an official HTTPS API origin "
                    "for the selected PayPal environment."
                )
        if self.app_env is AppEnv.PRODUCTION and not self.cors_allow_origins:
            raise ValueError(
                "APP_ENV=production requires CORS_ORIGINS "
                "(comma-separated https origins for the web app)."
            )
        return self

    @property
    def paypal_base_url(self) -> str:
        override = self.paypal_api_base_url.strip().rstrip("/")
        if override:
            return override
        return PAYPAL_BASE_URLS[self.paypal_env]

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id.strip() and self.paypal_client_secret.get_secret_value().strip())

    @property
    def ai_credentials_configured(self) -> bool:
        return bool(
            self.groq_api_key.get_secret_value().strip()
            or self.gemini_api_key.get_secret_value().strip()
            or self.openai_api_key.get_secret_value().strip()
        )

    @property
    def cors_allow_origins(self) -> list[str]:
        configured = [
            origin.strip().rstrip("/")
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]
        if configured:
            return configured
        if self.app_env is AppEnv.PRODUCTION:
            return []
        return ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — safe to call repeatedly as a FastAPI dependency."""
    return Settings()
