"""Corrections travel between the owner's computers (and to the phone copy) through git.

No new service and no new secret: the events are JSON files on a dedicated branch,
``paladex-corrections``, of the SAME repository each installation was cloned from (``origin`` of the
project folder). One file per event, ``events/<YYYY>/<event-id>.json``, so two computers writing at
the same time never touch the same file.

Only git "plumbing" is used, in the project folder, so the working tree, the index and the branch
the program runs from are never touched (the launcher keeps fast-forwarding that branch):

* read:  ``git ls-remote`` (where the branch is), ``git fetch origin
  +refs/heads/paladex-corrections:refs/remotes/origin/paladex-corrections`` (only when that commit is
  not here yet), ``git ls-tree`` and ``git cat-file --batch`` to read the files;
* write: ``git hash-object -w``, ``git update-index`` on a TEMPORARY index file (``GIT_INDEX_FILE``),
  ``git write-tree``, ``git commit-tree`` (parent = the fetched tip; an orphan commit creates the
  branch the first time) and ``git push origin <commit>:refs/heads/paladex-corrections`` - never
  forced: when another computer pushed meanwhile the push is rejected, the new tip is fetched, its
  events applied, and the commit rebuilt on it (a few attempts).

Git never asks anything: ``GIT_TERMINAL_PROMPT=0``, ``GCM_INTERACTIVE=never``, ssh in batch mode,
no standard input, a time limit on every command (as scripts/launch.py). Without git, without a
checkout with an ``origin``, without network or without credentials allowed to push, the events stay
on this computer with ``sync_status = pending_sync`` and the error, and the next synchronisation
(every ``PALADEX_CORRECTIONS_SYNC_MINUTES``, and after each new correction) tries again.

Nothing else is ever exported: supplier quotes, settings, keys and the database stay on the computer.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from ..config import PROJECT_ROOT, get_settings
from ..models import AppSetting, utcnow
from ..models_corrections import CorrectionEvent
from . import corrections

log = logging.getLogger(__name__)

BRANCH = "paladex-corrections"
REMOTE = "origin"
TRACKING_REF = f"refs/remotes/{REMOTE}/{BRANCH}"
STATE_SETTING = "corrections_sync_state"
NET_TIMEOUT = 90          # seconds: ls-remote, fetch, push
LOCAL_TIMEOUT = 30        # seconds: local plumbing
PUSH_ATTEMPTS = 4
COMMITTER_EMAIL = "paladex@localhost"
README = """# Paladex: correzioni / corrections

Questo ramo contiene solo le correzioni fatte nell'applicazione Paladex (un file JSON per correzione,
`events/<anno>/<id>.json`). Lo scrivono e lo leggono le installazioni di Paladex: non modificarlo a mano.

This branch only holds the corrections made in the Paladex application (one JSON file per correction,
`events/<year>/<id>.json`). Paladex installations write and read it: do not edit it by hand.
"""

_lock = threading.Lock()


class SyncError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code, self.message = code, message[:500]


MESSAGES = {
    "disabled": ("Scambio con gli altri computer non attivo: le correzioni restano su questo computer. "
                 "Si attiva una volta, su ogni computer, con l'interruttore «Scambia le correzioni».",
                 "Exchange with the other computers is off: corrections stay on this computer. It is switched "
                 "on once, on each computer, with the «Exchange corrections» switch."),
    "no_git": ("Git non è installato: le correzioni restano su questo computer finché non lo si installa.",
               "Git is not installed: corrections stay on this computer until it is."),
    "not_a_checkout": ("Questa cartella non è una copia git del progetto: le correzioni restano su questo computer.",
                       "This folder is not a git copy of the project: corrections stay on this computer."),
    "no_origin": ("La copia git non ha un 'origin': le correzioni restano su questo computer.",
                  "The git copy has no 'origin': corrections stay on this computer."),
    "network": ("Nessuna connessione con il repository: nuovo tentativo più tardi.",
                "The repository cannot be reached: retried later."),
    "credentials": ("Il repository ha rifiutato l'accesso: serve un account GitHub autorizzato a scrivere (vedere il README).",
                    "The repository refused access: a GitHub account allowed to write is needed (see the README)."),
    "timeout": ("Il repository non ha risposto in tempo: nuovo tentativo più tardi.",
                "The repository did not answer in time: retried later."),
    "push_rejected": ("Altri computer hanno scritto nello stesso momento: nuovo tentativo più tardi.",
                      "Other computers wrote at the same time: retried later."),
    "git_error": ("Errore di git: nuovo tentativo più tardi.", "Git error: retried later."),
}


def _classify(stderr: str) -> str:
    s = stderr.lower()
    if any(w in s for w in ("authentication failed", "could not read username", "could not read password",
                            "permission denied", "403", "401", "access denied", "terminal prompts disabled",
                            "repository not found", "invalid username or password", "not authorized")):
        return "credentials"
    if any(w in s for w in ("could not resolve", "unable to access", "connection refused", "timed out",
                            "network is unreachable", "failed to connect", "connection reset", "no route to host",
                            "could not connect", "ssl", "proxy")):
        return "network"
    return "git_error"


def redact_url(url: str | None) -> str | None:
    """Remote address without any user name or token in it."""
    if not url:
        return None
    url = re.sub(r"(?i)^(https?://)[^/@]*@", r"\1", url.strip())
    return url[:300]


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


def git_env(extra: dict | None = None) -> dict:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", LC_ALL="C", LANGUAGE="C")
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=20")
    env.pop("GIT_INDEX_FILE", None)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    if extra:
        env.update(extra)
    return env


@dataclass
class Git:
    root: Path
    exe: str

    def run(self, *args: str, timeout: int = LOCAL_TIMEOUT, input: bytes | None = None, env: dict | None = None,
            check: bool = True) -> subprocess.CompletedProcess:
        try:
            res = subprocess.run([self.exe, "-C", str(self.root), *args], input=input, capture_output=True,
                                 timeout=timeout, env=env or git_env(), check=False,
                                 stdin=None if input is not None else subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise SyncError("timeout", f"git {args[0]}: no answer within {timeout} s") from None
        except OSError as exc:
            raise SyncError("no_git", f"git {args[0]}: {exc}") from None
        if check and res.returncode != 0:
            err = res.stderr.decode("utf-8", "replace").strip()
            raise SyncError(_classify(err), f"git {args[0]}: {err[-400:]}")
        return res

    def out(self, *args: str, **kw) -> str:
        return self.run(*args, **kw).stdout.decode("utf-8", "replace").strip()

    # -- remote ---------------------------------------------------------------
    def remote_tip(self) -> str | None:
        """Commit the branch points to on the remote, or None when it does not exist yet."""
        text = self.out("ls-remote", "--heads", REMOTE, f"refs/heads/{BRANCH}", timeout=NET_TIMEOUT)
        for line in text.splitlines():
            sha, _, ref = line.partition("\t")
            if ref.strip() == f"refs/heads/{BRANCH}" and re.fullmatch(r"[0-9a-f]{40,64}", sha):
                return sha
        return None

    def has_commit(self, sha: str) -> bool:
        return self.run("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0

    def ensure_fetched(self, tip: str) -> None:
        if self.has_commit(tip):
            return
        self.run("fetch", "--no-tags", "--quiet", REMOTE, f"+refs/heads/{BRANCH}:{TRACKING_REF}", timeout=NET_TIMEOUT)
        if not self.has_commit(tip):          # the branch moved again between ls-remote and fetch
            raise SyncError("push_rejected", "the branch moved during the fetch")

    def push(self, commit: str) -> str:
        """'ok' | 'rejected' (someone pushed first). Raises SyncError for anything else."""
        res = self.run("push", "--quiet", "--no-verify", REMOTE, f"{commit}:refs/heads/{BRANCH}",
                       timeout=NET_TIMEOUT, check=False)
        if res.returncode == 0:
            self.run("update-ref", TRACKING_REF, commit, check=False)
            return "ok"
        err = res.stderr.decode("utf-8", "replace")
        if any(w in err for w in ("rejected", "non-fast-forward", "fetch first", "stale info", "failed to update ref",
                                  "cannot lock ref")):
            return "rejected"
        raise SyncError(_classify(err), f"git push: {err.strip()[-400:]}")

    # -- reading --------------------------------------------------------------
    def list_events(self, tip: str | None) -> list[str]:
        if not tip:
            return []
        out = self.run("ls-tree", "-r", "-z", "--name-only", tip, "--", "events").stdout.decode("utf-8", "replace")
        return [p for p in out.split("\0") if re.fullmatch(r"events/\d{4}/[0-9a-f-]{36}\.json", p)]

    def read_blobs(self, tip: str, paths: list[str]) -> dict[str, bytes]:
        if not paths:
            return {}
        data = self.run("cat-file", "--batch", input="".join(f"{tip}:{p}\n" for p in paths).encode()).stdout
        out: dict[str, bytes] = {}
        pos = 0
        for p in paths:
            nl = data.index(b"\n", pos)
            header = data[pos:nl].decode("utf-8", "replace").split()
            pos = nl + 1
            if len(header) == 3 and header[1] == "blob":
                size = int(header[2])
                out[p] = data[pos:pos + size]
                pos += size + 1
        return out

    # -- writing --------------------------------------------------------------
    def commit(self, tip: str | None, files: dict[str, bytes], message: str, author: str) -> str:
        """A commit holding the tip's files plus `files`, built on a temporary index (the
        repository's own index and working tree are not touched)."""
        name = re.sub(r"[<>\n\r\t]", " ", f"Paladex ({author})")[:100]
        with tempfile.TemporaryDirectory(prefix="paladex-corrections-") as td:
            env = git_env({"GIT_INDEX_FILE": str(Path(td) / "index"), "GIT_AUTHOR_NAME": name,
                           "GIT_AUTHOR_EMAIL": COMMITTER_EMAIL, "GIT_COMMITTER_NAME": name,
                           "GIT_COMMITTER_EMAIL": COMMITTER_EMAIL})
            if tip:
                self.run("read-tree", tip, env=env)
            else:
                self.run("read-tree", "--empty", env=env)
                files = {"README.md": README.encode("utf-8"), **files}
            lines = []
            for path, content in sorted(files.items()):
                sha = self.out("hash-object", "-w", "--stdin", input=content, env=env)
                lines.append(f"100644 {sha}\t{path}\n")
            self.run("update-index", "--add", "--index-info", input="".join(lines).encode(), env=env)
            tree = self.out("write-tree", env=env)
            args = ["commit-tree", "--no-gpg-sign", tree, "-m", message] + (["-p", tip] if tip else [])
            return self.out(*args, env=env)


# ---------------------------------------------------------------------------
# Availability and state
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    return Path(get_settings().corrections_git_dir or PROJECT_ROOT)


def availability() -> tuple[Git | None, str | None, str | None]:
    """(git, None, remote) when synchronisation can be tried; (None, reason code, None) otherwise.
    Local checks only (no network)."""
    if not get_settings().corrections_sync:
        return None, "disabled", None
    if os.environ.get("PYTEST_CURRENT_TEST") and repo_root().resolve() == PROJECT_ROOT.resolve():
        return None, "disabled", None           # a test never talks to the real repository's origin
    exe = shutil.which("git")
    if not exe:
        return None, "no_git", None
    root = repo_root()
    if not root.is_dir():
        return None, "not_a_checkout", None
    git = Git(root, exe)
    try:
        if git.run("rev-parse", "--git-dir", check=False).returncode != 0:
            return None, "not_a_checkout", None
        res = git.run("remote", "get-url", REMOTE, check=False)
    except SyncError as exc:
        return None, exc.code, None
    if res.returncode != 0:
        return None, "no_origin", None
    return git, None, redact_url(res.stdout.decode("utf-8", "replace"))


def _session():
    from ..db import session_scope

    return session_scope()


def get_state(session) -> dict:
    row = session.get(AppSetting, STATE_SETTING)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def _save_state(state: dict) -> None:
    with _session() as s:
        row = s.get(AppSetting, STATE_SETTING)
        if row is None:
            s.add(AppSetting(key=STATE_SETTING, value=state))
        else:
            row.value = state


def status(session) -> dict:
    """What GET /api/corrections/sync shows: settings, last pull/push, pending events, errors."""
    _git, reason, remote = availability()
    pending = session.scalars(select(CorrectionEvent).where(CorrectionEvent.origin == "local",
                                                            CorrectionEvent.sync_status == "pending_sync")).all()
    synced = session.scalar(select(CorrectionEvent.id).where(CorrectionEvent.sync_status == "synced").limit(1))
    state = get_state(session)
    err = state.get("error")
    return {
        "enabled": reason is None,
        "reason": reason,
        "reason_message_it": MESSAGES[reason][0] if reason in MESSAGES else None,
        "reason_message_en": MESSAGES[reason][1] if reason in MESSAGES else None,
        "remote": remote,
        "branch": BRANCH,
        "interval_minutes": get_settings().corrections_sync_minutes,
        "author": corrections.author_name(session),
        "device_id": corrections._setting(session, corrections.DEVICE_SETTING),   # created with the first event
        "pending": len(pending),
        "pending_events": [e.event_id for e in pending][:50],
        "any_synced": synced is not None,
        "running": _lock.locked(),
        "last_attempt_at": state.get("last_attempt_at"),
        "last_pull_at": state.get("last_pull_at"),
        "last_push_at": state.get("last_push_at"),
        "last_received": state.get("last_received"),
        "last_pushed": state.get("last_pushed"),
        "remote_tip": state.get("remote_tip"),
        "error": err,
    }


# ---------------------------------------------------------------------------
# Synchronisation
# ---------------------------------------------------------------------------


def _document_bytes(ev: CorrectionEvent) -> bytes:
    return (json.dumps(corrections.to_document(ev), ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def _write_lock():
    from ..collectors.runner import _write_lock as lock

    return lock


# Test events pushed by mistake to the real branch on 6 Nov 2026 (01:28-01:33 UTC) by a development
# test server, signed "Papà" but never made by anyone: never applied, wherever the branch still holds them.
IGNORED_EVENT_IDS = frozenset({
    "43831269-2249-46ef-a9ac-c9f069c04dc0", "502e4587-86b4-4ecb-9030-9745222d3e46",
    "55c18509-b1aa-4816-9c94-c976da8d39ad", "85faf767-dc9d-4183-9cf2-31539023bdd2",
    "c91727f4-628f-41d2-a58d-1d7b589d8c28", "cfd8f712-372b-4210-833f-d6c801739a48",
    "e80877e2-b3a0-4bf1-838a-99cef9b5140c", "eeb68a7a-6ce8-4206-be3c-c3df50a8786a",
    "f4d49125-5913-475f-a60c-3d305c77e19d",
})


def _pull(git: Git, tip: str | None) -> dict:
    """Read the events of the branch that this computer does not hold yet, store and apply them."""
    if not tip:
        with _write_lock(), _session() as s:
            return corrections.import_documents(s, [])
    git.ensure_fetched(tip)
    paths = git.list_events(tip)
    with _session() as s:
        known = set(s.scalars(select(CorrectionEvent.event_id)))
    paths = [p for p in paths if p.rsplit("/", 1)[-1][:-5] not in IGNORED_EVENT_IDS]
    wanted = [p for p in paths if p.rsplit("/", 1)[-1][:-5] not in known]
    docs = []
    invalid = 0
    for blob in git.read_blobs(tip, wanted).values():
        try:
            docs.append(json.loads(blob.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            invalid += 1
    with _write_lock(), _session() as s:
        res = corrections.import_documents(s, docs)
        # Events of this computer already on the branch (pushed before the database recorded it).
        present = {p.rsplit("/", 1)[-1][:-5] for p in paths}
        for ev in s.scalars(select(CorrectionEvent).where(CorrectionEvent.sync_status == "pending_sync")):
            if ev.event_id in present:
                ev.sync_status, ev.synced_at, ev.sync_error = "synced", utcnow(), None
    res["invalid"] += invalid
    res["present"] = len(paths)
    return res


def _push(git: Git, tip: str | None) -> tuple[int, str | None]:
    """Push the events made here that the branch does not have. Returns (number pushed, new tip)."""
    for _attempt in range(PUSH_ATTEMPTS):
        with _session() as s:
            pending = list(s.scalars(select(CorrectionEvent).where(
                CorrectionEvent.origin == "local", CorrectionEvent.sync_status == "pending_sync")
                .order_by(CorrectionEvent.created_at, CorrectionEvent.id)))
            files = {corrections.event_path(ev): _document_bytes(ev) for ev in pending}
            ids = [ev.event_id for ev in pending]
            author = corrections.author_name(s)
        if not files:
            return 0, tip
        present = set(git.list_events(tip))
        to_write = {p: b for p, b in files.items() if p not in present}
        commit = tip
        if to_write:
            n = len(to_write)
            msg = f"Paladex: {n} correzion{'e' if n == 1 else 'i'} / {n} correction{'' if n == 1 else 's'}"
            commit = git.commit(tip, to_write, msg, author)
            if git.push(commit) == "rejected":
                tip = git.remote_tip()
                _pull(git, tip)            # apply what the other computer wrote, then rebuild on it
                continue
        with _session() as s:
            for ev in s.scalars(select(CorrectionEvent).where(CorrectionEvent.event_id.in_(ids))):
                ev.sync_status, ev.synced_at, ev.sync_error = "synced", utcnow(), None
        return len(to_write), commit
    raise SyncError("push_rejected", f"push rejected {PUSH_ATTEMPTS} times")


def _mark_pending_error(code: str, message: str) -> None:
    text = f"{MESSAGES.get(code, MESSAGES['git_error'])[1]} ({code}) {message}".strip()[:1000]
    with _session() as s:
        for ev in s.scalars(select(CorrectionEvent).where(CorrectionEvent.sync_status == "pending_sync")):
            ev.sync_error = text


def sync_now(*, push: bool = True, trigger: str = "manual") -> dict:
    """Pull (and apply) the events of the branch, then push this computer's pending events.
    `push=False` only reads (the phone copy's job: `corrections-apply --from-git`). Never raises for
    git, network or credential problems: they are recorded in the state and on the pending events."""
    with _lock:
        return _sync(push=push, trigger=trigger)


def _sync(*, push: bool, trigger: str) -> dict:
    with _session() as s:
        state = get_state(s)
    state.update(last_attempt_at=corrections.iso_utc(utcnow()), trigger=trigger)
    git, reason, _remote = availability()
    if git is None:
        state["error"] = {"code": reason, "message_it": MESSAGES[reason][0], "message_en": MESSAGES[reason][1]}
        if reason != "disabled":
            _mark_pending_error(reason, "")
        _save_state(state)
        return {**state, "ok": False}
    try:
        tip = git.remote_tip()
        res = _pull(git, tip)
        state.update(last_pull_at=corrections.iso_utc(utcnow()), last_received=res, remote_tip=tip)
        if push:
            n, tip = _push(git, tip)
            state.update(last_push_at=corrections.iso_utc(utcnow()), last_pushed=n, remote_tip=tip)
        state["error"] = None
        ok = True
    except SyncError as exc:
        log.warning("corrections sync failed (%s): %s", exc.code, exc.message)
        it, en = MESSAGES.get(exc.code, MESSAGES["git_error"])
        state["error"] = {"code": exc.code, "message_it": it, "message_en": en, "detail": exc.message,
                          "at": corrections.iso_utc(utcnow())}
        if push:
            _mark_pending_error(exc.code, exc.message)
        ok = False
    _save_state(state)
    if ok and (state.get("last_received") or {}).get("received"):
        _after_received()
    return {**state, "ok": ok}


def _after_received() -> None:
    """New corrections change figures: the shared aggregates are rebuilt (server only)."""
    try:
        from ..api import memo

        memo.warm_in_background()
    except Exception:  # pragma: no cover
        log.debug("warm-up after corrections failed", exc_info=True)


def sync_in_background(trigger: str = "event") -> threading.Thread | None:
    """Push a new local event soon (the API answers at once)."""
    if not get_settings().corrections_sync:
        return None
    t = threading.Thread(target=_safe_sync, args=(trigger,), name="paladex-corrections-sync", daemon=True)
    t.start()
    return t


def _safe_sync(trigger: str) -> None:
    try:
        sync_now(push=True, trigger=trigger)
    except Exception:  # pragma: no cover - a background sync never crashes the server
        log.exception("corrections sync failed")


def schedule(scheduler) -> bool:
    """Add the periodic synchronisation (and one run shortly after start-up) to the server's
    scheduler. Nothing is scheduled when sync is off or this folder is not a git checkout."""
    from datetime import datetime, timedelta

    git, reason, _remote = availability()
    if git is None:
        log.info("corrections sync not scheduled: %s", reason)
        return False
    minutes = max(1, int(get_settings().corrections_sync_minutes or 15))
    scheduler.add_job(_safe_sync, "interval", minutes=minutes, args=["schedule"], id="corrections:sync",
                      replace_existing=True, coalesce=True, max_instances=1, misfire_grace_time=None,
                      next_run_time=datetime.now(scheduler.timezone) + timedelta(seconds=20))
    return True
