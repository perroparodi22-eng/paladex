"""Application settings.

All secrets live in environment variables (or a local `.env` file in the project root)
and are only ever read by the backend. Nothing here is sent to the browser except the
non-secret booleans exposed by `public_flags()`.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
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
    # Real data shipped with the app (built from a normal collection, merged once per version at
    # start-up so a new installation opens with data instead of empty pages; see services/starter.py).
    starter_data_enabled: bool = True
    starter_data_path: Path = Field(default=PROJECT_ROOT / "starter" / "paladex-starter.sqlite3.xz")
    # Generic client name: the company name is never sent to external websites.
    user_agent: str = "Paladex/0.1 (internal research tool)"
    http_timeout_seconds: float = 45.0

    # --- AI ---
    llm_provider: str = "none"  # "anthropic" | "openai" | "none"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    llm_max_articles_per_run: int = 40
    # "Other sources (non-official)": weekly AI web search for recent figures (services/findings_ai.py).
    # Off by default; the Sources page switch (app setting) overrides this value. Anthropic only.
    web_findings_ai: bool = False
    web_findings_ai_max_searches: int = 20
    web_findings_ai_model: str = "claude-haiku-5-5"

    # --- corrections by a person (services/corrections.py, corrections_sync.py) ---
    # Name shown on this computer's corrections ("corrected by ..."); the name typed on screen wins.
    user_name: str | None = None
    # Exchange corrections with the owner's other installations through the `paladex-corrections`
    # branch of the git repository this folder was cloned from. OFF unless switched on deliberately on
    # each computer (the switch on screen writes PALADEX_CORRECTIONS_SYNC=true to this computer's .env):
    # a test run, a copy of the folder or a second checkout must never publish anything by default.
    corrections_sync: bool = False
    corrections_sync_minutes: int = 15
    corrections_git_dir: Path | None = None     # the repository (default: the project folder)

    # --- data-source keys (all optional) ---
    comtrade_api_key: str | None = None
    usda_mmn_api_key: str | None = None
    usda_nass_api_key: str | None = None
    # api.data.gov key — used by USDA FAS GATS (US Census honey imports by origin)
    data_gov_api_key: str | None = None
    # US Census Bureau API key (free) — optional for the Census International Trade API collector
    # (us_census_trade); sent only as the `key` query parameter Census requires, redacted on storage.
    census_api_key: str | None = None
    # FAOSTAT Developer Portal account (free). Optional: without it FAOSTAT is read from the public
    # bulk downloads; with it the collector uses narrow API queries and adds bilateral trade (TM).
    faostat_username: str | None = None
    faostat_password: SecretStr | None = None

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
            "census_key": bool(self.census_api_key),
            "scheduler_enabled": self.scheduler_enabled,
        }


def env_file_path() -> Path:
    """The local `.env` file with the owner's settings and keys (PALADEX_ENV_FILE overrides it,
    e.g. in tests, so they never read or write the real file)."""
    return Path(os.environ.get("PALADEX_ENV_FILE") or PROJECT_ROOT / ".env")


@lru_cache
def get_settings() -> Settings:
    s = Settings(_env_file=str(env_file_path()))
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.raw_dir.mkdir(parents=True, exist_ok=True)
    return s
