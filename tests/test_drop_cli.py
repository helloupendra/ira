"""``ira drop``: sign in once, then send, list, fetch and delete from a terminal."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ira import dropcli
from ira.channels.http import create_app
from ira.cli import main

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
PIN = "4321"
URL = "https://ira.example.com"


@pytest.fixture
def world(tmp_path, monkeypatch):
    runtime = make_runtime(data_dir=tmp_path / "server")
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    runtime.guard.set_pin(PIN, user_id=owner.id)
    app = create_app(runtime, start_channels=False)

    def client(url, token=None):
        assert url == URL
        made = TestClient(app)
        if token:
            made.headers["Authorization"] = f"Bearer {token}"
        return made

    monkeypatch.setattr(dropcli, "make_client", client)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("IRA_URL", raising=False)
    monkeypatch.delenv("IRA_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)
    return runtime, owner


def login(monkeypatch, *, pin: str = PIN) -> int:
    answers = iter([PASSWORD, pin])
    monkeypatch.setattr(dropcli.getpass, "getpass", lambda prompt: next(answers))
    return main(["drop", "login", "--url", URL, "--email", "owner@example.com"])


def stdin(monkeypatch, data: bytes) -> None:
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(data)))


def test_send_list_get_and_delete(world, monkeypatch, capsys, tmp_path):
    runtime, owner = world
    assert main(["drop", "list"]) == 1
    assert "not signed in" in capsys.readouterr().err

    assert login(monkeypatch) == 0
    saved = tmp_path / "config" / "ira" / "client.json"
    assert oct(saved.stat().st_mode)[-3:] == "600" and json.loads(saved.read_text())["url"] == URL
    scopes = runtime.store.query("SELECT scopes FROM api_tokens WHERE revoked_at IS NULL")
    assert [r["scopes"] for r in scopes] == ["ask,drop"]
    open_sessions = runtime.store.query("SELECT 1 FROM sessions WHERE revoked_at IS NULL")
    assert open_sessions == []  # signed out again

    assert main(["drop", "send", "--text", "https://example.com/plan"]) == 0
    data = os.urandom(3000)
    (tmp_path / "plan.pdf").write_bytes(data)
    assert main(["drop", "send", "plan.pdf", "--caption", "v2"]) == 0
    stdin(monkeypatch, b"call the CA \x1b[31m")
    assert main(["drop", "send", "-"]) == 0
    stdin(monkeypatch, b"\x89PNG\x00\xff")
    assert main(["drop", "send", "-", "--name", "shot.png"]) == 0
    capsys.readouterr()

    assert main(["drop", "list"]) == 0
    listed = capsys.readouterr().out
    assert "plan.pdf (2.9 KB)  v2" in listed and "CLI" in listed
    assert "\x1b" not in listed  # a terminal never gets escape codes from an item
    items = runtime.drop.list(owner.id)
    shot, text, plan, link = items
    assert (shot.name, shot.mime, text.text) == ("shot.png", "image/png", "call the CA \x1b[31m")

    assert main(["drop", "get", str(plan.id)]) == 0
    assert (tmp_path / "plan (1).pdf").read_bytes() == data  # never over what is there
    assert main(["drop", "get", str(plan.id), "-o", "out"]) == 0
    assert (tmp_path / "out").read_bytes() == data
    capsys.readouterr()
    assert main(["drop", "get", str(link.id)]) == 0
    assert capsys.readouterr().out == "https://example.com/plan\n"

    assert main(["drop", "rm", str(plan.id)]) == 0
    assert runtime.drop.get(owner.id, plan.id) is None
    assert main(["drop", "get", str(plan.id)]) == 1
    assert "no such item" in capsys.readouterr().err
    assert not list(Path(tmp_path).glob("*.part"))


def test_signing_in_again_and_keys_that_cannot(world, monkeypatch, capsys):
    runtime, owner = world
    assert login(monkeypatch, pin="0000") == 1
    assert "PIN" in capsys.readouterr().err
    assert login(monkeypatch) == 0 and login(monkeypatch) == 0
    live = runtime.store.query("SELECT id FROM api_tokens WHERE revoked_at IS NULL")
    assert len(live) == 1  # the earlier token on this computer stopped

    siri, _ = runtime.accounts.create_token(owner, "Siri", ["ask"])
    monkeypatch.setenv("IRA_TOKEN", siri)
    assert main(["drop", "list"]) == 1
    assert "cannot use Drop" in capsys.readouterr().err

    assert main(["drop", "login", "--url", "http://ira.example.com", "--email", "x"]) == 1
    assert "https://" in capsys.readouterr().err
    assert main(["drop", "list", "--url", "http://ira.example.com"]) == 1  # never sent
    assert "https://" in capsys.readouterr().err
