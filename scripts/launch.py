"""Start Paladex: bring the program up to date, then start the application.

Run by the start scripts ("Avvia Paladex") with the application's own Python, after they have
created the environment on the first start. Steps:

1. Update. If this folder is a git checkout and git is installed: `git fetch` (gives up after
   90 s), then a fast-forward of the program files (`git merge --ff-only`, local and quick, so a
   time-out never stops git half-way through changing them). It never asks for a password and
   never merges; any problem (no internet, changes made by hand in the folder) only means that
   the current version starts. Data (`data/`) and keys (`.env`) are not part of the program and
   are never touched. To turn it off: create an empty file named `.no-auto-update` in this
   folder, or set PALADEX_AUTO_UPDATE=false in `.env`.
2. Requirements. When backend/requirements.txt changed since the last installation (an update
   added a library), they are installed again. If that fails and a library is missing, the
   window says so and waits instead of showing an error and closing.
3. Start: `python -m paladex serve` in backend/ (the browser opens by itself). Ctrl+C or closing
   the window stops it; if it stops with an error, the window waits so the message can be read.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
REQUIREMENTS = BACKEND / "requirements.txt"
STAMP = BACKEND / ".venv" / "paladex-requirements.sha256"
OFF = ("0", "false", "no", "off")
MIN_PYTHON = (3, 11)


def say(it: str, en: str) -> None:
    print(f"  {it}\n  {en}", flush=True)


def wait_for_enter() -> None:
    """Keep the window open (a double-clicked window closes as soon as the program ends)."""
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\n  Premere Invio per chiudere questa finestra. / Press Enter to close this window. ")
        except (EOFError, KeyboardInterrupt):
            pass


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
    return subprocess.run([git, *args], cwd=root, capture_output=True, text=True, timeout=timeout, env=env,
                          stdin=subprocess.DEVNULL)


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
        # The download may be cut short (slow or no connection); the files are then moved
        # forward locally, without a time limit that could stop git half-way through.
        if _git(git, root, "fetch", "--quiet", timeout=90).returncode != 0:
            return "failed"
        if _git(git, root, "merge", "--ff-only", "--quiet", "@{upstream}", timeout=900).returncode != 0:
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


def missing_libraries(requirements_file: Path = REQUIREMENTS) -> list[str]:
    """Libraries of requirements.txt that are not installed at all in this Python."""
    from importlib import metadata

    missing = []
    for line in requirements_file.read_text(encoding="utf-8").splitlines():
        name = re.split(r"[\s\[<>=!~;@]", line.split("#", 1)[0].strip(), maxsplit=1)[0]
        if not name or name.startswith("-"):
            continue
        try:
            metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
    return missing


def serve(argv: list[str]) -> int:
    proc = subprocess.Popen([sys.executable, "-m", "paladex", "serve", *argv], cwd=BACKEND)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        # Ctrl+C reached the application too: let it close properly (it finishes what it is
        # writing), and only force it after a while.
        try:
            proc.wait(timeout=20)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            proc.kill()
            proc.wait()
        return 0


def main(argv: list[str]) -> int:
    if sys.version_info < MIN_PYTHON:
        say("Questa installazione usa un Python troppo vecchio: installare Python 3.11 o superiore da "
            "https://www.python.org/downloads/, cancellare la cartella backend/.venv e riaprire Paladex.",
            "This installation uses a Python that is too old: install Python 3.11 or newer from "
            "https://www.python.org/downloads/, delete the backend/.venv folder and start Paladex again.")
        wait_for_enter()
        return 1
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
        missing = missing_libraries()
        if missing:
            names = ", ".join(missing[:3]) + (", ..." if len(missing) > 3 else "")
            say(f"Mancano alcune librerie e non è stato possibile installarle ({names}). "
                "Controllare la connessione internet e riaprire Paladex.",
                f"Some libraries are missing and could not be installed ({names}). "
                "Check the internet connection and start Paladex again.")
            wait_for_enter()
            return 1
        say("Attenzione: non è stato possibile installare le librerie aggiornate (connessione?).",
            "Warning: the updated libraries could not be installed (connection?).")
    code = serve(argv)
    if code != 0:
        say("Paladex si è fermato per un errore (vedere i messaggi qui sopra).",
            "Paladex stopped because of an error (see the messages above).")
        wait_for_enter()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
