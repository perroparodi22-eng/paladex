"""Start Paladex: bring the program up to date, then start the application.

Run by the start scripts ("Avvia Paladex") with the application's own Python, after they have
created the environment on the first start. Steps:

1. Update. If this folder is a git checkout and git is installed: `git pull --ff-only`. It never
   asks for a password, never merges and gives up after 90 s; any problem (no internet, changes
   made by hand in the folder) only means that the current version starts. Data (`data/`) and
   keys (`.env`) are not part of the program and are never touched. To turn it off: create an
   empty file named `.no-auto-update` in this folder, or set PALADEX_AUTO_UPDATE=false in `.env`.
2. Requirements. When backend/requirements.txt changed since the last installation (an update
   added a library), they are installed again.
3. Start: `python -m paladex serve` in backend/ (the browser opens by itself).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
REQUIREMENTS = BACKEND / "requirements.txt"
STAMP = BACKEND / ".venv" / "paladex-requirements.sha256"
OFF = ("0", "false", "no", "off")


def say(it: str, en: str) -> None:
    print(f"  {it}\n  {en}", flush=True)


def auto_update_enabled(root: Path = ROOT) -> bool:
    if (root / ".no-auto-update").exists():
        return False
    if os.environ.get("PALADEX_AUTO_UPDATE", "").strip().lower() in OFF:
        return False
    try:
        for line in (root / ".env").read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "PALADEX_AUTO_UPDATE" and value.strip().lower() in OFF:
                return False
    except OSError:
        pass
    return True


def _git(git: str, root: Path, *args: str, timeout: int) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    return subprocess.run([git, *args], cwd=root, capture_output=True, text=True, timeout=timeout, env=env)


def update(root: Path = ROOT) -> str:
    """'updated' | 'current' | 'failed' | 'no-git-checkout' | 'no-git' | 'disabled'."""
    if not auto_update_enabled(root):
        return "disabled"
    if not (root / ".git").exists():
        return "no-git-checkout"
    git = shutil.which("git")
    if not git:
        return "no-git"
    try:
        before = _git(git, root, "rev-parse", "HEAD", timeout=15).stdout.strip()
        pulled = _git(git, root, "pull", "--ff-only", "--quiet", timeout=90)
        if pulled.returncode != 0:
            return "failed"
        after = _git(git, root, "rev-parse", "HEAD", timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "failed"
    return "updated" if after and after != before else "current"


def requirements(requirements_file: Path = REQUIREMENTS, stamp: Path = STAMP) -> str:
    """'ok' (unchanged) | 'installed' | 'failed'."""
    digest = hashlib.sha256(requirements_file.read_bytes()).hexdigest()
    try:
        if stamp.read_text(encoding="utf-8").strip() == digest:
            return "ok"
    except OSError:
        pass
    try:
        done = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q",
                               "-r", str(requirements_file)], timeout=900)
    except (OSError, subprocess.TimeoutExpired):
        return "failed"
    if done.returncode != 0:
        return "failed"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(digest + "\n", encoding="utf-8")
    return "installed"


def main(argv: list[str]) -> int:
    status = update()
    if status == "updated":
        say("Paladex è stato aggiornato all'ultima versione.", "Paladex was updated to the latest version.")
    elif status == "failed":
        say("Aggiornamento automatico non riuscito (connessione o modifiche nella cartella): avvio la versione attuale.",
            "Automatic update not possible (connection, or changes in the folder): starting the current version.")
    elif status in ("no-git-checkout", "no-git"):
        say("Aggiornamenti automatici non attivi: serve git (vedere README, «Aggiornare Paladex»).",
            "Automatic updates are off: git is needed (see README, 'Aggiornare Paladex').")
    if requirements() == "failed":
        say("Attenzione: non è stato possibile installare le librerie aggiornate (connessione?).",
            "Warning: the updated libraries could not be installed (connection?).")
    try:
        return subprocess.call([sys.executable, "-m", "paladex", "serve", *argv], cwd=BACKEND)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
