"""Pairing: trade the one-time code from the Devices page for this Mac's own token.

Someone pastes the pairing link (``https://ira.example.com/pair#code=ABCD-EFGH``)
or types the code; the companion asks the server, and keeps the token it gets
in the Keychain. The code works once, within 10 minutes.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from ira_mac import __version__, tls

LINK = re.compile(r"^(https?://[^#\s]+?)/pair#code=([A-Za-z0-9-]{8,20})$")
CODE = re.compile(r"^[A-Za-z0-9-]{8,20}$")


class PairError(RuntimeError):
    pass


@dataclass
class Paired:
    server: str
    token: str
    device_id: int
    label: str
    skills: list[str]


def parse(entry: str, server: str | None) -> tuple[str, str]:
    """(server, code) from a pasted link, or from a code and the server given."""
    entry = entry.strip()
    link = LINK.match(entry)
    if link:
        return link.group(1).rstrip("/"), link.group(2)
    if CODE.match(entry):
        if not server:
            raise PairError("say which server this code is for (--server)")
        return server.rstrip("/"), entry
    raise PairError("paste the pairing link or type the 8-character code")


ASK = "Your Ira's address, as at the start of the pairing link (https://...): "


def choose(entry: str, known: list[str | None], ask: Callable[[str], str]) -> tuple[str, str]:
    """(server, code): a pasted link names its server; a typed code uses the first
    known one (--server, the download's server.txt, the last pairing), or asks."""
    entry = entry.strip()
    server = next((s for s in known if s), None)
    if CODE.match(entry) and not server:
        server = ask(ASK).strip()
        if not server:
            raise PairError("say which server this code is for")
    return parse(entry, server)


def check_server(server: str) -> str:
    parts = urlsplit(server)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise PairError("the server address must start with http:// or https://")
    local = parts.hostname in ("127.0.0.1", "localhost", "::1")
    if parts.scheme == "http" and not local:
        raise PairError("use https:// for a server on another machine")
    return server.rstrip("/")


def exchange(
    server: str, code: str, *, timeout: float = 20, opener=urllib.request.urlopen
) -> Paired:
    server = check_server(server)
    body = json.dumps({"code": code, "kind": "mac"}).encode()
    request = urllib.request.Request(
        f"{server}/v1/devices/pair",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": f"ira-mac/{__version__}"},
    )
    try:
        with opener(request, timeout=timeout, context=tls.context()) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 410:
            raise PairError("that code is used, expired or mistyped; make a new one") from None
        if exc.code == 429:
            raise PairError("too many wrong codes; wait 15 minutes") from None
        raise PairError(f"the server answered HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise PairError(f"could not reach {server}: {tls.reason(exc)}") from None
    except ValueError:
        raise PairError(f"{server} did not answer like an Ira server") from None
    try:
        return Paired(
            server=server,
            token=str(data["token"]),
            device_id=int(data["device_id"]),
            label=str(data.get("label") or "My Mac"),
            skills=list(data.get("skills") or []),
        )
    except (KeyError, TypeError, ValueError):
        raise PairError("the server's answer did not hold a device token") from None
