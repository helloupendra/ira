"""A connection's address is checked when it connects, every time: DNS that later answers
with this machine or the cloud's metadata service never gets a connection there."""

from __future__ import annotations

import socket

import pytest

from ira.connectors import mcp
from ira.connectors.imap import Mailbox
from ira.tools.registry import ToolError

pytestmark = pytest.mark.anyio


def dns(monkeypatch, *addresses: str) -> None:
    def answer(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]

    monkeypatch.setattr(socket, "getaddrinfo", answer)


def test_an_address_is_public_or_refused(monkeypatch):
    dns(monkeypatch, "93.184.216.34")
    assert mcp.resolve("mcp.example.com", 443) == "93.184.216.34"
    for inside in ("169.254.169.254", "127.0.0.1", "10.0.0.5", "::1"):
        dns(monkeypatch, "93.184.216.34", inside)  # one bad answer is enough
        with pytest.raises(ToolError, match="private network"):
            mcp.resolve("mcp.example.com", 443)
    assert mcp.resolve("mcp.example.com", 443, allow_private=True) == "93.184.216.34"


async def test_each_connection_goes_to_the_address_checked_then(monkeypatch):
    import httpcore2
    import httpx2

    backend = mcp.pinned_backend(allow_private=False)
    seen: list[str] = []

    async def connect(host, port, timeout=None, local_address=None, socket_options=None):
        seen.append(host)
        raise httpcore2.ConnectError("stop here")

    backend.inner.connect_tcp = connect
    dns(monkeypatch, "93.184.216.34")
    with pytest.raises(httpcore2.ConnectError, match="stop here"):
        await backend.connect_tcp("mcp.example.com", 443)
    assert seen == ["93.184.216.34"]  # the checked address, not the name again

    # Later the name points at the metadata service: no connection is made at all.
    dns(monkeypatch, "169.254.169.254")
    client = mcp.pinned_client({})
    try:
        with pytest.raises(httpx2.ConnectError, match="private network"):
            await client.get("https://mcp.example.com/mcp")
    finally:
        await client.aclose()


def test_a_saved_mailbox_is_checked_when_it_opens(monkeypatch):
    dns(monkeypatch, "127.0.0.1")
    with pytest.raises(ToolError, match="private network"):
        Mailbox("imap.example.com", "me@example.com", "app-password")._open()
