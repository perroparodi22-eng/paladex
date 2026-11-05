"""Saving an optional key in the local `.env` file, from the Sources page.

The owner pastes a free key (USDA NASS, US Census, api.data.gov, UN Comtrade, an AI provider)
into the interface instead of editing a file by hand. The value is written only to `.env` on
this computer (git-ignored), never returned to the browser and never logged. Comments and every
other line of the file are kept; a commented placeholder line (`# PALADEX_X=`) is reused.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .config import PROJECT_ROOT, env_file_path

# What a pasted key may contain: no spaces, quotes, line breaks or shell characters.
VALUE_RE = re.compile(r"^[A-Za-z0-9._~+/=:@-]{1,400}$")
LLM_PROVIDERS = ("anthropic", "openai", "none")


def _starting_lines(path: Path) -> list[str]:
    if path.exists():
        return path.read_text(encoding="utf-8").splitlines()
    example = PROJECT_ROOT / ".env.example"
    return example.read_text(encoding="utf-8").splitlines() if example.exists() else []


def set_env_value(name: str, value: str | None, path: Path | None = None) -> Path:
    """Set `name=value` in the .env file (an empty value clears it). Returns the file written."""
    if not re.fullmatch(r"PALADEX_[A-Z0-9_]+", name):
        raise ValueError(f"not a Paladex setting: {name!r}")
    if value and not VALUE_RE.match(value):
        raise ValueError("invalid characters in the value")
    path = path or env_file_path()
    line_re = re.compile(rf"^\s*(#\s*)?{re.escape(name)}\s*=")
    new_line = f"{name}={value or ''}"
    out: list[str] = []
    placed = False
    for line in _starting_lines(path):
        if line_re.match(line):
            if not placed:
                out.append(new_line)          # first active or commented line becomes the setting
                placed = True
            elif not line.lstrip().startswith("#"):
                continue                      # a later active duplicate would override it: drop it
            else:
                out.append(line)
            continue
        out.append(line)
    if not placed:
        out.append(new_line)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out) + "\n")
        try:
            os.chmod(tmp, 0o600)              # keys: readable by the owner only (no-op on Windows)
        except OSError:  # pragma: no cover
            pass
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path
