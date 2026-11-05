"""`python -m paladex serve` started twice, or on a port another program uses (cli.port_owner)."""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from paladex import cli


def _server(body: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def no_server(monkeypatch):
    """The real server must not start in these tests."""
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("the server was started"))
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))
    return opened


def test_port_owner():
    paladex, other = _server(json.dumps({"ok": True}).encode()), _server(b"<html>another program</html>")
    try:
        assert cli.port_owner("127.0.0.1", paladex.server_port) == "paladex"
        assert cli.port_owner("127.0.0.1", other.server_port) == "other"
        assert cli.port_owner("0.0.0.0", paladex.server_port) == "paladex"
    finally:
        paladex.shutdown(), other.shutdown()
    assert cli.port_owner("127.0.0.1", _free_port()) == ""


def test_second_start_shows_the_running_paladex(db, no_server, capsys):
    srv = _server(b'{"ok": true}')
    try:
        assert cli.main(["serve", "--port", str(srv.server_port)]) == 0
    finally:
        srv.shutdown()
    assert no_server == [f"http://127.0.0.1:{srv.server_port}"]
    assert "già aperto" in capsys.readouterr().out


def test_port_used_by_another_program_is_explained(db, no_server, capsys):
    srv = _server(b"hello")
    try:
        assert cli.main(["serve", "--no-browser", "--port", str(srv.server_port)]) == 1
    finally:
        srv.shutdown()
    out = capsys.readouterr().out
    assert "altro programma" in out and f"PALADEX_PORT={srv.server_port + 1}" in out and no_server == []
