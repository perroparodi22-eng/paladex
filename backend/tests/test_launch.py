"""The start step (scripts/launch.py): self-update with git, reinstall requirements when they
change, never block the start. Uses real temporary git repositories."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
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
