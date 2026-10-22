"""Log redaction, the Keychain (the token never in argv), and pairing."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from ira_mac import __version__, config, tls
from ira_mac.keychain import Keychain, KeychainError
from ira_mac.logs import RedactingFormatter, redact
from ira_mac.pair import PairError, check_server, choose, exchange, parse
from ira_mac.tools import Toolbox

from .conftest import FakeBrowser

TOKEN = "irad_" + "Ab1-_" * 8 + "xyz"


# --- logs ------------------------------------------------------------------------------


def test_redact_drops_queries_and_masks_tokens_and_codes():
    line = (
        "read https://drive.example.com/upload?session=abc123&id=9#frag with "
        f"{TOKEN} and /pair#code=ABCD-EFGH"
    )
    cleaned = redact(line)
    assert "abc123" not in cleaned and "#frag" not in cleaned
    assert "https://drive.example.com/upload" in cleaned
    assert TOKEN not in cleaned and "irad_***" in cleaned
    assert "ABCD-EFGH" not in cleaned
    assert redact("x" * 900).endswith("...")


def test_tools_never_log_page_text_or_addresses(caplog):
    page = {
        "title": "Upload",
        "url": "https://drive.example.com/up?token=SECRET-QUERY",
        "text": "PRIVATE PAGE TEXT about a customer",
        "progress": {"bars": [{"percent": 63}]},
    }
    tabs = [
        {
            "id": 7,
            "title": "Upload",
            "url": "https://drive.example.com/up?token=SECRET-QUERY",
            "active": True,
            "focused": True,
        }
    ]
    tools = Toolbox(FakeBrowser(tabs, {7: page}), lambda *a: None)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    logger = logging.getLogger("ira_mac")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with caplog.at_level(logging.INFO):
            result = asyncio.run(tools.call("chrome_read_tab", {"match": "upload"}))
            asyncio.run(tools.call("chrome_list_tabs", {}))
    finally:
        logger.removeHandler(handler)
    assert result["text"].startswith("PRIVATE PAGE TEXT")
    assert result["tab"]["url"] == "https://drive.example.com/up"  # no query, even for Ira
    logged = stream.getvalue() + caplog.text
    assert "read tab 7" in logged
    assert "PRIVATE PAGE TEXT" not in logged and "SECRET-QUERY" not in logged


# --- the Keychain ----------------------------------------------------------------------


class FakeSecurity:
    def __init__(self):
        self.calls = []
        self.stored = None

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs.get("input")))
        if args[1] == "-i":
            words = kwargs["input"].split()
            self.stored = words[words.index("-w") + 1]
            return SimpleNamespace(returncode=0, stdout="")
        if args[1] == "find-generic-password":
            if self.stored is None:
                return SimpleNamespace(returncode=44, stdout="")
            return SimpleNamespace(returncode=0, stdout=self.stored + "\n")
        if args[1] == "delete-generic-password":
            found, self.stored = self.stored is not None, None
            return SimpleNamespace(returncode=0 if found else 44, stdout="")
        raise AssertionError(args)


def test_the_token_goes_to_the_keychain_on_stdin_never_in_argv():
    security = FakeSecurity()
    keychain = Keychain(run=security)
    assert keychain.load() is None
    keychain.save(TOKEN)
    assert keychain.load() == TOKEN
    for args, _stdin in security.calls:
        assert all(TOKEN not in arg for arg in args)
        assert args[0] == "/usr/bin/security"
    save_args, save_stdin = security.calls[1]
    assert save_args == ["/usr/bin/security", "-i"] and TOKEN in save_stdin
    assert "-s ira-mac -a device" in save_stdin
    assert keychain.delete() is True and keychain.load() is None
    with pytest.raises(KeychainError):
        keychain.save("not a token")


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/security").exists(), reason="macOS only"
)
def test_a_real_keychain_file():
    folder = Path(tempfile.mkdtemp())
    path = str(folder / "test.keychain-db")
    subprocess.run(["/usr/bin/security", "create-keychain", "-p", "test", path], check=True)
    try:
        subprocess.run(["/usr/bin/security", "unlock-keychain", "-p", "test", path], check=True)
        keychain = Keychain(keychain=path, service="ira-mac-test")
        keychain.save(TOKEN)
        assert keychain.load() == TOKEN
        assert keychain.delete() is True and keychain.load() is None
    finally:
        subprocess.run(["/usr/bin/security", "delete-keychain", path], check=False)
        shutil.rmtree(folder, ignore_errors=True)


# --- pairing ---------------------------------------------------------------------------


def test_parse_a_link_or_a_code():
    assert parse("https://ira.example.com/pair#code=ABCD-EFGH", None) == (
        "https://ira.example.com",
        "ABCD-EFGH",
    )
    assert parse("  abcd-efgh ", "http://127.0.0.1:8765/") == ("http://127.0.0.1:8765", "abcd-efgh")
    with pytest.raises(PairError, match="which server"):
        parse("ABCDEFGH", None)
    with pytest.raises(PairError, match="paste the pairing link"):
        parse("hello there", "http://127.0.0.1:8765")


def test_plain_http_only_for_this_machine():
    assert check_server("http://127.0.0.1:8765/") == "http://127.0.0.1:8765"
    assert check_server("https://ira.example.com") == "https://ira.example.com"
    with pytest.raises(PairError, match="https"):
        check_server("http://ira.example.com")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_exchange_posts_the_code_and_reads_the_token():
    seen = {}

    def opener(request, timeout, context=None):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data)
        seen["agent"] = request.get_header("User-agent")  # Cloudflare refuses Python's own
        seen["checks"] = context.verify_mode == ssl.CERT_REQUIRED
        body = {"device_id": 3, "token": TOKEN, "label": "Office Mac", "skills": ["chrome"]}
        return FakeResponse(json.dumps(body).encode())

    paired = exchange("https://ira.example.com", "ABCD-EFGH", opener=opener)
    assert seen == {
        "url": "https://ira.example.com/v1/devices/pair",
        "body": {"code": "ABCD-EFGH", "kind": "mac"},
        "agent": f"ira-mac/{__version__}",
        "checks": True,
    }
    assert (paired.token, paired.device_id, paired.skills) == (TOKEN, 3, ["chrome"])

    def gone(request, timeout, context=None):
        raise urllib.error.HTTPError(request.full_url, 410, "Gone", {}, None)

    with pytest.raises(PairError, match="expired or mistyped"):
        exchange("https://ira.example.com", "ABCD-EFGH", opener=gone)

    def untrusted(request, timeout, context=None):
        failure = ssl.SSLCertVerificationError(
            1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
        )
        raise urllib.error.URLError(failure)

    with pytest.raises(PairError, match=r"certificate verify failed.*Run ./install.sh again"):
        exchange("https://ira.example.com", "ABCD-EFGH", opener=untrusted)

    def refused(request, timeout, context=None):
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    with pytest.raises(
        PairError, match="could not reach https://ira.example.com: Connection refused"
    ):
        exchange("https://ira.example.com", "ABCD-EFGH", opener=refused)


def test_a_typed_code_uses_the_first_known_server_or_asks():
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return "https://ira.example.com "

    link = "https://ira.example.net/pair#code=ABCD-EFGH"
    from_link = choose(link, ["https://ira.example.org"], ask)
    assert from_link == ("https://ira.example.net", "ABCD-EFGH")
    assert choose("ABCD-EFGH", [None, "https://ira.example.org", "http://127.0.0.1:8765"], ask) == (
        "https://ira.example.org",
        "ABCD-EFGH",
    )
    assert asked == []
    # Nothing known: it asks, never guesses this machine.
    assert choose("ABCD-EFGH", [None, None, ""], ask) == ("https://ira.example.com", "ABCD-EFGH")
    assert len(asked) == 1
    with pytest.raises(PairError, match="which server"):
        choose("ABCD-EFGH", [], lambda prompt: "  ")


def test_the_downloads_server_txt_is_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv("IRA_MAC_HOME", str(tmp_path))
    assert config.given_server() is None
    (tmp_path / "server.txt").write_text("https://ira.example.com\n", encoding="utf-8")
    assert config.given_server() == "https://ira.example.com"
    (tmp_path / "server.txt").write_text("not an address\n", encoding="utf-8")
    assert config.given_server() is None
    unpaired = config.load(tmp_path / "missing.json")
    assert unpaired.server == ""
    with pytest.raises(ValueError, match="not paired"):
        unpaired.websocket_url()


def test_certificates_come_from_somewhere_even_on_a_bare_python(monkeypatch):
    real = ssl.create_default_context
    calls = []

    def bare(*args, **kwargs):
        calls.append(kwargs.get("cafile"))
        if kwargs.get("cafile"):
            return real(*args, **kwargs)
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # no authorities, like python.org's

    monkeypatch.setitem(sys.modules, "truststore", None)  # not installed
    monkeypatch.setattr(tls.ssl, "create_default_context", bare)
    context = tls.context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert context.cert_store_stats()["x509_ca"] > 0
    assert calls[0] is None and calls[1]  # the default first, then a bundle


def test_the_websocket_checks_certificates_only_for_wss(monkeypatch):
    from websockets.asyncio import client

    from ira_mac.daemon import websocket_connect

    seen = []

    async def connect(url, **kwargs):
        seen.append((url, "ssl" in kwargs, kwargs["user_agent_header"]))
        return object()

    monkeypatch.setattr(client, "connect", connect)
    asyncio.run(websocket_connect("wss://ira.example.com/v1/devices/ws", TOKEN))
    asyncio.run(websocket_connect("ws://127.0.0.1:8765/v1/devices/ws", TOKEN))
    agent = f"ira-mac/{__version__}"
    assert seen == [
        ("wss://ira.example.com/v1/devices/ws", True, agent),
        ("ws://127.0.0.1:8765/v1/devices/ws", False, agent),
    ]
