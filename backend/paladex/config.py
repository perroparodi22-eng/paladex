"""Application settings.

All secrets live in environment variables (or a local `.env` file in the project root)
and are only ever read by the backend. Nothing here is sent to the browser except the
non-secret booleans exposed by `public_flags()`.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PALADEX_",
        env_file=(str(PROJECT_ROOT / ".env"),),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- app ---
    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    frontend_dist: Path = Field(default=PROJECT_ROOT / "frontend" / "dist")
    scheduler_enabled: bool = True
    # Run a full collection shortly after start-up if the last run is older than this.
    startup_collect_if_older_than_hours: int = 6
    user_agent: str = (
        "ParodiGroup-HoneyIntelligence/0.1 (internal research tool; contact: info@parodigroup.local)"
    )
    http_timeout_seconds: float = 45.0

    # --- AI ---
    llm_provider: str = "none"  # "anthropic" | "openai" | "none"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    llm_max_articles_per_run: int = 40

    # --- data-source keys (all optional) ---
    comtrade_api_key: str | None = None
    usda_mmn_api_key: str | None = None
    usda_nass_api_key: str | None = None
    # api.data.gov key — used by USDA FAS GATS (US Census honey imports by origin)
    data_gov_api_key: str | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "paladex.sqlite3"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    def llm_enabled(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        return False

    def public_flags(self) -> dict:
        return {
            "llm_enabled": self.llm_enabled(),
            "llm_provider": self.llm_provider if self.llm_enabled() else None,
            "comtrade_key": bool(self.comtrade_api_key),
            "usda_mmn_key": bool(self.usda_mmn_api_key),
            "usda_nass_key": bool(self.usda_nass_api_key),
            "data_gov_key": bool(self.data_gov_api_key),
            "scheduler_enabled": self.scheduler_enabled,
        }


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.raw_dir.mkdir(parents=True, exist_ok=True)
    return s
