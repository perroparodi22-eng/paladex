"""Command line: `python -m paladex <command>`.

  serve                 start the app (API + interface) and open the browser
  init-db               create / upgrade the database and reference tables
  collect [keys...]     run collectors now (all if none given); --force re-parses unchanged files
  sources               list sources and their status
  seed-demo / purge-demo   add or remove clearly-labelled demonstration data
  starter-import        merge the real starter data shipped in starter/ (serve does it automatically)
  starter-build --from DB [--out FILE]   (developers) build the starter data from a real database
  corrections-sync      exchange corrections with the owner's other computers now (git branch paladex-corrections)
  corrections-apply --from-git   only read and apply the corrections of that branch (the phone copy's job)
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="paladex")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--port", type=int)
    sub.add_parser("init-db")
    c = sub.add_parser("collect")
    c.add_argument("keys", nargs="*")
    c.add_argument("--force", action="store_true")
    sub.add_parser("sources")
    sub.add_parser("seed-demo")
    sub.add_parser("purge-demo")
    sub.add_parser("starter-import")
    sb = sub.add_parser("starter-build")
    sb.add_argument("--from", dest="src", required=True)
    sb.add_argument("--out")
    sub.add_parser("corrections-sync")
    ca = sub.add_parser("corrections-apply")
    ca.add_argument("--from-git", dest="from_git", action="store_true", required=True,
                    help="read the paladex-corrections branch of the repository's origin (never writes to it)")
    args = p.parse_args(argv)

    from .config import get_settings
    from .db import init_db, session_scope

    settings = get_settings()

    if args.cmd == "starter-build":
        from pathlib import Path

        from .services import starter

        meta = starter.build(Path(args.src), Path(args.out) if args.out else settings.starter_data_path)
        print(json.dumps(meta, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "serve":
        import uvicorn

        port = args.port or settings.port
        url = f"http://{settings.host}:{port}"
        running = port_owner(settings.host, port)
        if running == "paladex":
            # Started twice (e.g. a second double-click): show the one already open.
            print(f"\n  Paladex è già aperto: lo mostro nel browser ({url}).\n"
                  f"  Paladex is already running: showing it in the browser ({url}).\n", flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        if running == "other":
            print(f"\n  La porta {port} è già usata da un altro programma. Chiuderlo, oppure scegliere un'altra porta "
                  f"nel file .env (per esempio PALADEX_PORT={port + 1}), e riaprire Paladex.\n"
                  f"  Port {port} is already used by another program. Close it, or choose another port in the .env "
                  f"file (for example PALADEX_PORT={port + 1}), and start Paladex again.\n", flush=True)
            return 1
        print(f"\n  Parodi Group — Honey Intelligence\n  Apri il browser su / Open: {url}\n  (Chiudi questa finestra per fermare l'applicazione)\n")
        # Real starter data first (once per version, before the server and the scheduler start):
        # a new installation opens with data instead of empty pages.
        init_db()
        _import_starter_data(verbose=True)
        if not args.no_browser:
            threading.Timer(2.0, lambda: webbrowser.open(url)).start()
        uvicorn.run("paladex.main:app", host=settings.host, port=port, log_level="info")
        return 0

    init_db()
    if args.cmd == "init-db":
        print(f"Database ready at {settings.db_path}")
    elif args.cmd == "collect":
        from .collectors.registry import IMPORT_ERRORS, all_collectors
        from .collectors.runner import post_collection_hooks, run_collector

        keys = args.keys or [c.key for c in all_collectors()]
        for k in keys:
            res = run_collector(k, trigger="cli", force=args.force)
            print(json.dumps(res, ensure_ascii=False, default=str))
        post_collection_hooks()
        for mod, err in IMPORT_ERRORS.items():
            print(f"IMPORT ERROR {mod}: {err}", file=sys.stderr)
    elif args.cmd == "sources":
        from sqlalchemy import select

        from .models import Source

        with session_scope() as sess:
            for src in sess.scalars(select(Source).order_by(Source.category)):
                print(f"{src.key:28} {src.category:11} last={src.last_run_status or '-':10} "
                      f"published={src.latest_published_at or '-'}  {src.name}")
    elif args.cmd == "seed-demo":
        from .api.common import set_setting
        from .services.demo import seed_demo

        with session_scope() as sess:
            n = seed_demo(sess)
            set_setting(sess, "show_demo", True)
        print(f"Inserted {n} DEMO rows (clearly labelled). Remove with: purge-demo")
    elif args.cmd == "starter-import":
        res = _import_starter_data(verbose=True)
        if res is None:
            print("Nothing to import (no starter data shipped, or this version is already merged).")
    elif args.cmd in ("corrections-sync", "corrections-apply"):
        from .services import corrections_sync

        res = corrections_sync.sync_now(push=args.cmd == "corrections-sync", trigger="cli")
        print(json.dumps(res, ensure_ascii=False, default=str))
        return 0 if res.get("ok") or (res.get("error") or {}).get("code") == "disabled" else 1
    elif args.cmd == "purge-demo":
        from .api.common import set_setting
        from .services.demo import purge_demo

        with session_scope() as sess:
            n = purge_demo(sess)
            set_setting(sess, "show_demo", False)
        print(f"Deleted {n} demo rows")
    return 0


def port_owner(host: str, port: int) -> str:
    """Who listens on host:port already: 'paladex' (a running Paladex), 'other' (another
    program) or '' (free)."""
    import socket
    import urllib.request

    if host in ("", "0.0.0.0", "::"):
        host = "127.0.0.1"
    try:
        with socket.create_connection((host, port), timeout=1):
            pass
    except OSError:
        return ""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never through a proxy
    name = f"[{host}]" if ":" in host else host
    try:
        with opener.open(f"http://{name}:{port}/api/health", timeout=3) as res:
            if json.loads(res.read(1000) or b"{}") == {"ok": True}:
                return "paladex"
    except Exception:  # noqa: BLE001 - anything else listening there is "another program"
        pass
    return "other"


def _import_starter_data(verbose: bool = False) -> dict | None:
    from .services import starter

    def progress(_stage: str) -> None:
        if verbose:
            print("  Preparazione dei dati iniziali (solo la prima volta, meno di un minuto)...\n"
                  "  Preparing the initial data (first time only, under a minute)...", flush=True)

    res = starter.import_if_needed(progress=progress)
    if res and verbose:
        n = sum(res["inserted"].values())
        when = (res.get("data_collected_until") or "")[:16].replace("T", " ")
        if n == 0:
            print("  I dati iniziali sono già tutti presenti. / The initial data is already all here.\n", flush=True)
            return res
        print(f"  Dati reali pronti: {n} valori dalle fonti ufficiali (raccolti fino al {when} UTC).\n"
              f"  Ora l'applicazione li aggiorna da sola in background.\n"
              f"  Real data ready: {n} values from the official sources (collected up to {when} UTC);"
              f" the app now refreshes them in the background.\n", flush=True)
    return res


if __name__ == "__main__":
    sys.exit(main())
