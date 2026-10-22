"""The clients as downloads: Ira for Mac, from the project's latest release."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ira import clients
from ira.channels.http import create_app

from .conftest import make_runtime


def test_the_list_names_ira_for_mac_on_the_latest_release(registry):
    with TestClient(create_app(make_runtime(registry=registry), start_channels=False)) as client:
        listed = client.get("/v1/downloads").json()
    assert [d["name"] for d in listed] == ["Ira.dmg"]
    mac = listed[0]
    assert mac["title"] == "Ira for Mac"
    assert mac["url"] == "https://github.com/helloupendra/ira/releases/latest/download/Ira.dmg"
    assert mac["available"] is False  # the server does not carry it
    assert "Applications" in mac["description"]


def test_a_download_link_goes_to_the_release(registry):
    with TestClient(create_app(make_runtime(registry=registry), start_channels=False)) as client:
        response = client.get("/v1/downloads/Ira.dmg", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == clients.DOWNLOADS[0].url
        assert client.get("/v1/downloads/other.zip").status_code == 404


def test_the_retired_downloads_say_where_to_go(registry):
    with TestClient(create_app(make_runtime(registry=registry), start_channels=False)) as client:
        for name in ("ira-mac.zip", "ira-chrome-extension.zip"):
            response = client.get(f"/v1/downloads/{name}", follow_redirects=False)
            assert response.status_code == 404
            assert "Ira for Mac" in response.json()["detail"]
