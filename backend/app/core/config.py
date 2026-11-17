"""Application settings.

All configuration comes from environment variables (or backend/.env in development).
Nothing secret is ever hard-coded: the same code runs locally, in Docker and on AWS,
only the environment changes.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General ---
    APP_NAME: str = "MealConnect API"
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True
    # None = automatic (on outside production). Set true to show /docs on a demo deployment.
    API_DOCS_ENABLED: bool | None = None
    # Sandbox "pay" endpoint for the mock gateway. None = automatic (off in production).
    SANDBOX_PAYMENTS_ENABLED: bool | None = None

    # --- Infrastructure ---
    DATABASE_URL: str
    TEST_DATABASE_URL: str | None = None
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Security ---
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Cost factor: each +1 doubles hashing time. 12 ≈ 0.2 s (slow for attackers);
    # the test suite lowers it to 4 so hundreds of hashes stay fast.
    BCRYPT_ROUNDS: int = 12
    # --- Caching, rate limiting, background jobs ---
    CACHE_ENABLED: bool = True
    CACHE_TTL_SECONDS: int = 120  # restaurant lists / search
    MENU_CACHE_TTL_SECONDS: int = 300
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "300/minute"  # per client IP, every API route
    RATE_LIMIT_LOGIN: str = "5/minute"  # per IP + email
    RATE_LIMIT_REGISTER: str = "10/hour"  # per IP
    # Proxies in front of the API (Nginx/ALB) whose X-Forwarded-For we trust.
    TRUSTED_PROXY_COUNT: int = 0
    EMAIL_BACKEND: Literal["console"] = "console"  # Phase 11 can add "ses"

    # --- Payments ---
    # "mock" = built-in sandbox gateway (signed webhooks, no external account needed).
    # Phase 8 adds a real provider in test mode behind the same interface.
    PAYMENT_PROVIDER: Literal["mock", "razorpay"] = "mock"
    PAYMENT_WEBHOOK_SECRET: str
    # Razorpay test-mode keys (Dashboard -> Settings -> API Keys, "Test Mode").
    RAZORPAY_KEY_ID: str | None = None
    RAZORPAY_KEY_SECRET: str | None = None
    RAZORPAY_API_URL: str = "https://api.razorpay.com/v1"
    CURRENCY: str = "INR"

    # Comma-separated list, e.g. "http://localhost:5173,https://mealconnect.example.com"
    CORS_ORIGINS: str = "http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def docs_enabled(self) -> bool:
        return (
            self.API_DOCS_ENABLED if self.API_DOCS_ENABLED is not None else not self.is_production
        )

    @property
    def sandbox_payments_enabled(self) -> bool:
        if self.PAYMENT_PROVIDER != "mock":
            return False  # never fake payments when a real gateway is configured
        if self.SANDBOX_PAYMENTS_ENABLED is not None:
            return self.SANDBOX_PAYMENTS_ENABLED
        return not self.is_production


@lru_cache
def get_settings() -> Settings:
    """Read settings once and reuse them (cached)."""
    return Settings()


settings = get_settings()
