"""Serving the built console: its own routes load index.html, missing assets stay 404."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ira import web
from ira.channels.http import create_app

from .conftest import make_runtime

INDEX = "<!doctype html><title>console</title>"


def _client(tmp_path, monkeypatch, registry) -> TestClient:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX, encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(web, "ADMIN_DIR", tmp_path)
    return TestClient(create_app(make_runtime(registry=registry), start_channels=False))


def test_console_routes_load_the_console(tmp_path, monkeypatch, registry):
    with _client(tmp_path, monkeypatch, registry) as client:
        for path in ("/admin/", "/admin/setup", "/admin/invite", "/admin/users/3"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.text == INDEX, path


def test_console_assets_are_served_and_missing_ones_are_404(tmp_path, monkeypatch, registry):
    with _client(tmp_path, monkeypatch, registry) as client:
        assert client.get("/admin/assets/app.js").text == "console.log(1)"
        assert client.get("/admin/assets/gone.js").status_code == 404


def test_without_a_build_admin_shows_the_placeholder(tmp_path, monkeypatch, registry):
    monkeypatch.setattr(web, "ADMIN_DIR", tmp_path)  # empty: no console built
    with TestClient(create_app(make_runtime(registry=registry), start_channels=False)) as client:
        response = client.get("/admin")
        assert response.status_code == 200
        assert INDEX not in response.text


def test_admin_without_a_slash_redirects_to_the_console(tmp_path, monkeypatch, registry):
    with _client(tmp_path, monkeypatch, registry) as client:
        response = client.get("/admin", follow_redirects=False)
        assert response.status_code == 308
        assert response.headers["location"] == "/admin/"
        response = client.get("/admin?next=users", follow_redirects=False)
        assert response.headers["location"] == "/admin/?next=users"
        assert client.head("/admin", follow_redirects=False).status_code == 308
        assert client.get("/admin").text == INDEX


def test_the_web_apps_files_ask_the_server_before_a_cache_reuses_them(registry):
    # Sent with no rule, Cloudflare kept the old app.js and style.css for four hours.
    with TestClient(create_app(make_runtime(registry=registry), start_channels=False)) as client:
        for path in ("/", "/app.js", "/style.css", "/sw.js", "/pair"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers["cache-control"] == "no-cache", path


def test_the_consoles_hashed_assets_are_kept_and_its_page_is_not(tmp_path, monkeypatch, registry):
    with _client(tmp_path, monkeypatch, registry) as client:
        assert client.get("/admin/assets/app.js").headers["cache-control"] == (
            "public, max-age=31536000, immutable"
        )
        for path in ("/admin/", "/admin/setup"):
            assert client.get(path).headers["cache-control"] == "no-cache", path
        assert "immutable" not in client.get("/admin/assets/gone.js").headers.get(
            "cache-control", ""
        )


@pytest.mark.anyio
async def test_a_windows_path_to_a_hashed_asset_is_kept_too(tmp_path, monkeypatch):
    # Starlette joins the path with the system's separator: assets\app.js on Windows.
    from starlette.responses import Response

    from ira.channels import http

    async def found(self, path, scope):
        return Response("x")

    monkeypatch.setattr(http.StaticFiles, "get_response", found)
    files = http.ConsoleFiles(directory=tmp_path)
    response = await files.get_response("assets\\app.js", {"type": "http"})
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
