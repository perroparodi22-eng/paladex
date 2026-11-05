"""Paladex online copy, last check before publishing: no secret may appear in the copy.

    python scripts/mirror/scan_secrets.py <directory>

Gathers every secret the backend can see (API keys and passwords from the environment and from
the project's .env, read through the backend's own settings) plus any environment variable whose
name looks like a secret, then searches every file under <directory> for each value. Exits 1 if
one is found. Secret values are never printed, only the variable name and the file.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.I)
MIN_LEN = 8


def secrets() -> dict[str, str]:
    found: dict[str, str] = {}
    for name, value in os.environ.items():
        if SECRET_NAME.search(name) and value and len(value) >= MIN_LEN:
            found[f"env:{name}"] = value
    try:
        sys.path.insert(0, str(ROOT / "backend"))
        from paladex.config import Settings  # noqa: PLC0415 - optional: works without the backend too

        s = Settings()
        for name in type(s).model_fields:
            if not re.search(r"(key|password|secret|token)$", name):
                continue
            v = getattr(s, name, None)
            v = v.get_secret_value() if hasattr(v, "get_secret_value") else v
            if isinstance(v, str) and len(v) >= MIN_LEN:
                found[f"settings:{name}"] = v
    except Exception as exc:  # noqa: BLE001 - the environment scan above still runs
        print(f"  (backend settings not readable: {type(exc).__name__}; environment variables only)")
    return found


def main(directory: Path) -> int:
    values = secrets()
    files = [p for p in sorted(directory.rglob("*")) if p.is_file()]
    hits = []
    for p in files:
        data = p.read_bytes()
        for name, value in values.items():
            if value.encode() in data:
                hits.append((name, p))
    print(f"  secret scan: {len(values)} secret value(s) checked in {len(files)} file(s)")
    for name, p in hits:
        print(f"  SECRET FOUND: {name} appears in {p.relative_to(directory)}")
    return 1 if hits else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(Path(sys.argv[1])))
