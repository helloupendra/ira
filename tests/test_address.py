"""Where the server listens and where people open it: the bound port and public_url."""

from __future__ import annotations

import pytest
import uvicorn
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.cli import main
from ira.config import ConfigError, Settings, load_settings

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.delenv("IRA_PUBLIC_URL", raising=False)
    path = tmp_path / "ira.yaml"
    path.write_text("data_dir: ./data\nchannels:\n  http: {port: 8765}\n", encoding="utf-8")
    return str(path)


def serve(config: str, monkeypatch, *flags: str) -> dict:
    """Run `ira serve` without binding anything, and read the channels as the console does."""
    seen: dict = {}

    def fake_run(app, host, port, **kwargs):
        runtime = app.state.runtime
        owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
        session, _ = runtime.accounts.start_session(owner)
        with TestClient(app) as client:
            channels = client.get(
                "/v1/admin/channels", headers={"Authorization": f"Bearer {session}"}
            ).json()
        seen.update(bound=(host, port), channels={c["name"]: c for c in channels})

    monkeypatch.setattr(uvicorn, "run", fake_run)
    assert main(["--config", config, "serve", *flags]) == 0
    return seen


def test_channels_report_the_host_and_port_serve_bound(config, monkeypatch, capsys):
    seen = serve(config, monkeypatch, "--host", "0.0.0.0", "--port", "8811")
    assert seen["bound"] == ("0.0.0.0", 8811)
    http = seen["channels"]["http"]
    assert http["address"] == {
        "host": "0.0.0.0",
        "port": 8811,
        "configured_host": "127.0.0.1",
        "configured_port": 8765,
        "public_url": None,
        "url": "http://127.0.0.1:8811",
    }
    assert (http["detail"]["host"], http["detail"]["port"]) == ("0.0.0.0", 8811)
    assert seen["channels"]["telegram"]["address"] is None
    assert "listening on http://0.0.0.0:8811" in capsys.readouterr().out


def test_without_flags_the_config_is_what_is_bound(config, monkeypatch):
    http = serve(config, monkeypatch)["channels"]["http"]["address"]
    assert (http["host"], http["port"], http["url"]) == ("127.0.0.1", 8765, "http://127.0.0.1:8765")


def test_public_url_from_the_environment_is_reported_and_used(config, monkeypatch, capsys):
    monkeypatch.setenv("IRA_PUBLIC_URL", "https://ira.example.com/")
    http = serve(config, monkeypatch, "--port", "8812")["channels"]["http"]["address"]
    assert http["public_url"] == "https://ira.example.com"
    assert http["url"] == "https://ira.example.com" and http["port"] == 8812
    out = capsys.readouterr().out
    # The setup banner sends the owner to the public address, code in the fragment.
    assert "https://ira.example.com/" in out and "#code=" in out
    assert "http://127.0.0.1:8812/" not in out.split("No account exists yet")[1]


def test_public_url_in_ira_yaml_and_its_checks(tmp_path, monkeypatch):
    monkeypatch.delenv("IRA_PUBLIC_URL", raising=False)
    path = tmp_path / "ira.yaml"
    path.write_text("channels:\n  http: {public_url: 'https://desk.example.com/'}\n")
    assert load_settings(path).channels.http.public_url == "https://desk.example.com"

    monkeypatch.setenv("IRA_PUBLIC_URL", "http://192.0.2.10:8765")
    assert load_settings(path).channels.http.public_url == "http://192.0.2.10:8765"
    monkeypatch.setenv("IRA_PUBLIC_URL", "desk.example.com")
    with pytest.raises(ConfigError, match="IRA_PUBLIC_URL"):
        load_settings(path)

    monkeypatch.delenv("IRA_PUBLIC_URL")
    for bad in ("ftp://desk.example.com", "https://desk.example.com/?x=1", "https://"):
        path.write_text(f"channels:\n  http: {{public_url: '{bad}'}}\n")
        with pytest.raises(ConfigError, match="public_url"):
            load_settings(path)


def test_invitations_carry_the_whole_link_when_public_url_is_set(registry):
    settings = Settings.model_validate(
        {"data_dir": "unused", "channels": {"http": {"public_url": "https://ira.example.com"}}}
    )
    runtime = make_runtime(registry=registry, settings=settings)
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    session, _ = runtime.accounts.start_session(owner)
    headers = {"Authorization": f"Bearer {session}"}
    with TestClient(create_app(runtime, start_channels=False)) as client:
        body = {"email": "desk@example.com", "role": "staff"}
        created = client.post("/v1/admin/users/invites", json=body, headers=headers).json()
    assert created["url"] == f"https://ira.example.com{created['path']}"
    assert created["path"].startswith("/admin/invite#token=")

    plain = make_runtime(registry=registry)
    owner = plain.accounts.create_first_owner("owner@example.com", PASSWORD)
    session, _ = plain.accounts.start_session(owner)
    with TestClient(create_app(plain, start_channels=False)) as client:
        created = client.post(
            "/v1/admin/users/invites",
            json={"email": "desk@example.com", "role": "staff"},
            headers={"Authorization": f"Bearer {session}"},
        ).json()
    assert created["url"] is None
