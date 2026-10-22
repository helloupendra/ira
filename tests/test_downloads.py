"""The clients as downloads: the zips' contents, and the public routes."""

from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from ira import clients
from ira.channels.http import create_app

from .conftest import make_runtime


def names(data: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(data)).namelist()


def test_the_mac_zip_holds_the_installer_and_the_extension_only():
    data = clients.build("ira-mac.zip")
    inside = names(data)
    assert "ira-mac/install.sh" in inside and "ira-mac/ira_mac/daemon.py" in inside
    assert "ira-mac/chrome-extension/manifest.json" in inside
    assert not any("/tests/" in n or "/test/" in n or "node_modules" in n for n in inside)
    info = zipfile.ZipFile(io.BytesIO(data)).getinfo("ira-mac/install.sh")
    assert (info.external_attr >> 16) & 0o777 == 0o755
    assert clients.build("ira-mac.zip") == data  # the same bytes every time


def test_the_routes_are_public_and_serve_zips(registry):
    with TestClient(create_app(make_runtime(registry=registry), start_channels=False)) as client:
        listed = client.get("/v1/downloads").json()
        assert [d["name"] for d in listed] == ["ira-mac.zip", "ira-chrome-extension.zip"]
        assert all(d["available"] and d["url"].startswith("/v1/downloads/") for d in listed)
        response = client.get("/v1/downloads/ira-chrome-extension.zip")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert "ira-chrome-extension/reader.js" in names(response.content)
        assert client.get("/v1/downloads/other.zip").status_code == 404


def test_without_the_sources_the_releases_page_is_named(registry, monkeypatch):
    monkeypatch.setattr(clients, "root", lambda: None)
    with TestClient(create_app(make_runtime(registry=registry), start_channels=False)) as client:
        listed = client.get("/v1/downloads").json()
        assert listed[0]["available"] is False and "releases" in listed[0]["url"]
