"""Pasting an optional key in the interface writes it to the local .env file only."""
from __future__ import annotations

import re

import pytest

from paladex import envfile


@pytest.fixture()
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setenv("PALADEX_ENV_FILE", str(path))
    return path


def test_set_value_keeps_comments_and_reuses_the_placeholder(env_file):
    env_file.write_text("# comment\nPALADEX_PORT=8765\n# PALADEX_CENSUS_API_KEY=\nPALADEX_USDA_NASS_API_KEY=\n")
    envfile.set_env_value("PALADEX_CENSUS_API_KEY", "abc123")
    envfile.set_env_value("PALADEX_USDA_NASS_API_KEY", "DEF-456")
    assert env_file.read_text() == ("# comment\nPALADEX_PORT=8765\nPALADEX_CENSUS_API_KEY=abc123\n"
                                    "PALADEX_USDA_NASS_API_KEY=DEF-456\n")
    envfile.set_env_value("PALADEX_CENSUS_API_KEY", None)           # cleared, line kept
    assert "PALADEX_CENSUS_API_KEY=\n" in env_file.read_text()


def test_missing_file_starts_from_the_example_and_duplicates_are_removed(env_file):
    envfile.set_env_value("PALADEX_DATA_GOV_API_KEY", "k1")
    text = env_file.read_text()
    assert text.count("PALADEX_DATA_GOV_API_KEY=k1") == 1 and "PALADEX_SCHEDULER_ENABLED" in text  # from .env.example
    env_file.write_text("PALADEX_DATA_GOV_API_KEY=old\nPALADEX_DATA_GOV_API_KEY=older\n")
    envfile.set_env_value("PALADEX_DATA_GOV_API_KEY", "new")
    assert env_file.read_text() == "PALADEX_DATA_GOV_API_KEY=new\n"


@pytest.mark.parametrize("bad", ["two words", "a\nPALADEX_DATA_DIR=/tmp", "x'y", 'q"', "$(rm)"])
def test_values_that_could_change_other_settings_are_refused(env_file, bad):
    with pytest.raises(ValueError):
        envfile.set_env_value("PALADEX_CENSUS_API_KEY", bad)
    assert not env_file.exists()


def test_api_saves_the_key_and_uses_it_right_away(env_file, api):
    before = {k["setting"]: k["configured"] for k in api.get("/api/quality/keys").json()["keys"]}
    assert before.get("usda_nass_api_key") is False
    res = api.put("/api/quality/keys/usda_nass_api_key", json={"value": "  NASS-KEY-1  "})
    assert res.status_code == 200 and res.json() == {"setting": "usda_nass_api_key", "configured": True}
    assert "PALADEX_USDA_NASS_API_KEY=NASS-KEY-1" in env_file.read_text()
    after = {k["setting"]: k["configured"] for k in api.get("/api/quality/keys").json()["keys"]}
    assert after["usda_nass_api_key"] is True
    assert "NASS-KEY-1" not in api.get("/api/quality/keys").text          # never sent back
    assert api.put("/api/quality/keys/usda_nass_api_key", json={"value": ""}).json()["configured"] is False


def test_api_refuses_unknown_settings_bad_values_and_form_posts(env_file, api):
    assert api.put("/api/quality/keys/data_dir", json={"value": "/tmp"}).status_code == 404
    assert api.put("/api/quality/keys/census_api_key", json={"value": "a b"}).status_code == 422
    assert api.put("/api/quality/keys/llm_provider", json={"value": "other"}).status_code == 422
    assert api.put("/api/quality/keys/llm_provider", json={"value": "anthropic"}).status_code == 200
    # A plain HTML form (what another website could make the browser send) is not accepted.
    assert api.put("/api/quality/keys/census_api_key", data={"value": "x"}).status_code == 422
    assert not re.search(r"^PALADEX_DATA_DIR=", env_file.read_text(), re.M)   # only the example's comment


def test_ai_service_and_key_from_the_interface_apply_without_restart(env_file, api, monkeypatch):
    """The Assistant / Sources panel: provider + key saved in .env, the status follows at once."""
    monkeypatch.delenv("PALADEX_LLM_PROVIDER", raising=False)       # the test fixture pins it in the environment
    from paladex.config import get_settings

    get_settings.cache_clear()
    st = api.get("/api/assistant/status").json()
    assert st["llm_enabled"] is False and st["provider_setting"] == "none"
    assert st["keys_saved"] == {"anthropic": False, "openai": False}
    assert api.put("/api/quality/keys/anthropic_api_key", json={"value": "sk-ant-test-123"}).json()["configured"] is True
    assert api.put("/api/quality/keys/llm_provider", json={"value": "anthropic"}).status_code == 200
    st = api.get("/api/assistant/status").json()
    assert st["llm_enabled"] is True and st["provider"] == "anthropic" and st["provider_setting"] == "anthropic"
    assert st["keys_saved"] == {"anthropic": True, "openai": False}
    assert "sk-ant-test-123" not in api.get("/api/assistant/status").text   # never sent back
    assert api.get("/api/meta").json()["flags"]["llm_enabled"] is True
    # switched off from the panel: the key stays saved, the AI is off
    api.put("/api/quality/keys/llm_provider", json={"value": "none"})
    st = api.get("/api/assistant/status").json()
    assert st["llm_enabled"] is False and st["keys_saved"]["anthropic"] is True
    text = env_file.read_text()
    assert "PALADEX_LLM_PROVIDER=none" in text and "PALADEX_ANTHROPIC_API_KEY=sk-ant-test-123" in text
    # "delete the saved key"
    assert api.put("/api/quality/keys/anthropic_api_key", json={"value": ""}).json()["configured"] is False
    assert api.get("/api/assistant/status").json()["keys_saved"]["anthropic"] is False
