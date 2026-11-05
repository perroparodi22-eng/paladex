"""The start step (scripts/launch.py): self-update with git, reinstall requirements when they
change, never block the start. Uses real temporary git repositories."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("paladex_launch", ROOT / "scripts" / "launch.py")
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repos(tmp_path):
    """An 'origin' (what GitHub holds) and the owner's clone of it."""
    origin, work, clone = tmp_path / "origin.git", tmp_path / "work", tmp_path / "clone"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(tmp_path, "init", "-q", str(work))
    for k, v in (("user.email", "t@example.org"), ("user.name", "t")):
        git(work, "config", k, v)
    (work / "app.txt").write_text("v1\n")
    git(work, "add", "."), git(work, "commit", "-qm", "v1"), git(work, "branch", "-M", "main")
    git(work, "remote", "add", "origin", str(origin)), git(work, "push", "-q", "-u", "origin", "main")
    git(tmp_path, "clone", "-q", "-b", "main", str(origin), str(clone))
    return work, clone


def publish(work: Path, text: str) -> None:
    (work / "app.txt").write_text(text)
    git(work, "commit", "-qam", text.strip()), git(work, "push", "-q")


def test_pulls_a_new_version_then_reports_current(repos):
    work, clone = repos
    publish(work, "v2\n")
    assert launch.update(clone) == "updated"
    assert (clone / "app.txt").read_text() == "v2\n"
    assert launch.update(clone) == "current"


def test_local_changes_or_no_connection_never_block_the_start(repos, tmp_path):
    work, clone = repos
    publish(work, "v2\n")
    (clone / "app.txt").write_text("edited by hand\n")          # would be overwritten: git refuses
    assert launch.update(clone) == "failed"
    assert (clone / "app.txt").read_text() == "edited by hand\n"
    git(clone, "checkout", "--", "app.txt")
    git(clone, "remote", "set-url", "origin", str(tmp_path / "unreachable.git"))
    assert launch.update(clone) == "failed"


def test_ignored_data_and_keys_survive_and_opt_out_is_respected(repos, monkeypatch):
    work, clone = repos
    (clone / ".gitignore").write_text("data/\n.env\n")
    (clone / "data").mkdir()
    (clone / "data" / "paladex.sqlite3").write_text("db")
    (clone / ".env").write_text("PALADEX_USDA_NASS_API_KEY=k\n")
    publish(work, "v2\n")
    assert launch.update(clone) == "updated"
    assert (clone / "data" / "paladex.sqlite3").read_text() == "db" and "NASS" in (clone / ".env").read_text()
    publish(work, "v3\n")
    (clone / ".env").write_text("PALADEX_AUTO_UPDATE=false\n")
    assert launch.update(clone) == "disabled"
    (clone / ".env").unlink()
    (clone / ".no-auto-update").write_text("")
    assert launch.update(clone) == "disabled"
    (clone / ".no-auto-update").unlink()
    monkeypatch.setenv("PALADEX_AUTO_UPDATE", "off")
    assert launch.update(clone) == "disabled"


def test_a_downloaded_zip_is_not_updated(tmp_path):
    assert launch.update(tmp_path) == "no-git-checkout"


def test_requirements_are_reinstalled_only_when_they_change(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(launch.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    req, stamp = tmp_path / "requirements.txt", tmp_path / ".venv" / "stamp"
    req.write_text("fastapi\n")
    assert launch.requirements(req, stamp) == "installed" and len(calls) == 1
    assert launch.requirements(req, stamp) == "ok" and len(calls) == 1
    req.write_text("fastapi\nnewlib\n")
    assert launch.requirements(req, stamp) == "installed" and len(calls) == 2
    monkeypatch.setattr(launch.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1))
    req.write_text("fastapi\nnewlib\nother\n")
    assert launch.requirements(req, stamp) == "failed"           # offline: the start goes on


def test_missing_libraries_reads_the_requirement_names(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("# comment\nfastapi>=0.110\nuvicorn[standard]>=0.29\npydantic-settings>=2.2\n\n"
                   "surely-not-installed-lib>=1  # comment\n-r other.txt\n")
    assert launch.missing_libraries(req) == ["surely-not-installed-lib"]


def _no_update(monkeypatch, requirements: str = "ok") -> None:
    monkeypatch.setattr(launch, "update", lambda: "current")
    monkeypatch.setattr(launch, "requirements", lambda: requirements)


def test_a_failed_installation_is_explained_and_the_app_is_not_started(monkeypatch, capsys):
    _no_update(monkeypatch, "failed")
    monkeypatch.setattr(launch, "missing_libraries", lambda: ["fastapi"])
    monkeypatch.setattr(launch, "serve", lambda argv: pytest.fail("started without its libraries"))
    assert launch.main([]) == 1
    assert "connessione internet" in capsys.readouterr().out
    monkeypatch.setattr(launch, "missing_libraries", lambda: [])        # only an update failed: start anyway
    monkeypatch.setattr(launch, "serve", lambda argv: 0)
    assert launch.main([]) == 0


def test_a_stop_with_an_error_is_reported_and_a_too_old_python_refused(monkeypatch, capsys):
    _no_update(monkeypatch)
    monkeypatch.setattr(launch, "serve", lambda argv: 3)
    assert launch.main([]) == 3 and "errore" in capsys.readouterr().out
    monkeypatch.setattr(launch, "serve", lambda argv: 0)
    assert launch.main([]) == 0 and "errore" not in capsys.readouterr().out
    monkeypatch.setattr(launch.sys, "version_info", (3, 10, 12))
    assert launch.main([]) == 1 and "3.11" in capsys.readouterr().out


class _FakeServer:
    def __init__(self, second_wait):
        self.waits, self.killed, self.second_wait = [], False, second_wait

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if len(self.waits) == 1:
            raise KeyboardInterrupt                        # Ctrl+C reaches both processes
        if len(self.waits) == 2 and self.second_wait is not None:
            raise self.second_wait
        return 0

    def kill(self):
        self.killed = True


@pytest.mark.parametrize("second_wait, killed", [(None, False), (subprocess.TimeoutExpired("x", 20), True)])
def test_ctrl_c_lets_the_server_close_properly(monkeypatch, second_wait, killed):
    proc = _FakeServer(second_wait)
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: proc)
    assert launch.serve([]) == 0
    assert proc.waits[:2] == [None, 20] and proc.killed is killed


def test_launchers_survive_an_update_while_running_and_stay_in_step():
    bat = (ROOT / "Avvia Paladex.bat").read_bytes()
    assert b"\n" not in bat.replace(b"\r\n", b"")                     # CRLF only: cmd misreads LF files
    # The last command runs as one block: an update may rewrite the file while it runs.
    assert b"(backend\\.venv\\Scripts\\python.exe scripts\\launch.py & exit /b)" in bat
    sh = (ROOT / "start.sh").read_bytes()
    assert sh == (ROOT / "Avvia Paladex.command").read_bytes() and b"\r" not in sh
    assert b'exec backend/.venv/bin/python scripts/launch.py "$@"' in sh


@pytest.mark.skipif(shutil.which("bash") is None or sys.platform == "win32", reason="needs bash")
def test_start_script_explains_a_missing_or_too_old_python(tmp_path):
    """Only an old Python on the computer (e.g. 3.9): a clear message, nothing installed."""
    app, bin_dir = tmp_path / "Paladex app", tmp_path / "bin"
    (app / "backend").mkdir(parents=True)
    bin_dir.mkdir()
    shutil.copy(ROOT / "start.sh", app / "start.sh")
    old = bin_dir / "python3"
    old.write_text("#!/bin/sh\nexit 1\n")                              # fails the 3.11 check
    old.chmod(0o755)
    for tool in ("dirname", "uname", "rm", "cp"):
        (bin_dir / tool).symlink_to(shutil.which(tool))
    # Without the Homebrew folders the script adds (this machine's own Python must not be found).
    script = (app / "start.sh").read_text().replace('export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"', "")
    (app / "start.sh").write_text(script)
    res = subprocess.run([shutil.which("bash"), str(app / "start.sh")], capture_output=True, text=True,
                         env={"PATH": str(bin_dir), "HOME": str(tmp_path)}, timeout=60)
    assert res.returncode == 1 and "Python 3.11 o superiore non trovato" in res.stdout
    assert not (app / "backend" / ".venv").exists()
