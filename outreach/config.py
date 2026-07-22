from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_base_url: str = "http://localhost:8000"
    site_base_url: str = "https://www.olmemtech.com"
    database_url: str
    cron_secret: str = Field(min_length=16)
    token_secret: str = Field(min_length=16)
    admin_password: str | None = None

    openai_api_key: str
    openai_model: str = "gpt-5-mini"

    tavily_api_key: str | None = None
    prospect_feed_url: str | None = None
    prospect_feed_token: str | None = None
    discovery_regions: str = "Kenosha WI,Racine WI,Milwaukee WI,Northeast Illinois"
    max_discoveries_per_run: int = Field(default=20, ge=1, le=100)
    max_research_per_run: int = Field(default=8, ge=1, le=50)

    outreach_catalog_url: str | None = None
    site_max_pages: int = Field(default=40, ge=5, le=200)
    prospect_max_pages: int = Field(default=8, ge=2, le=30)

    min_fit_score: int = Field(default=80, ge=50, le=100)
    autonomous_send: bool = False
    daily_send_limit: int = Field(default=8, ge=1, le=50)
    contact_cooldown_days: int = Field(default=120, ge=30, le=730)
    allow_named_public_emails: bool = False

    sendgrid_api_key: str
    sending_from_email: str
    reply_to_email: str = "jeff@olmemtech.com"
    sendgrid_event_public_key: str | None = None
    verify_sendgrid_webhook: bool = True
    track_opens: bool = True
    track_clicks: bool = True

    business_name: str = "Olmem Technical Solutions"
    business_postal_address: str

    lead_sync_url: str | None = None
    lead_sync_secret: str | None = None

    @field_validator("site_base_url", "app_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def regions(self) -> List[str]:
        return [item.strip() for item in self.discovery_regions.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
