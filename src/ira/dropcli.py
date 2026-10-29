"""``ira drop``: your Drop from a terminal, on any computer that can reach your Ira.

ira drop login --url https://ira.example.com   once: your email, password and PIN
ira drop send plan.pdf [--caption "v2"]        a file
ira drop send --text "call the CA"             text, or a link
pbpaste | ira drop send -                      what comes in on stdin
ira drop list
ira drop get 42 [-o path]                      a file is saved here; text is printed
ira drop rm 42                                 gone from every device

The address and token come from IRA_URL and IRA_TOKEN, else from what ``login`` saved
in ~/.config/ira/client.json, readable by you alone. ``login`` makes a token that may
ask and use your Drop, nothing else, with your PIN as a new device does.
"""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import getpass
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from ira import __version__
from ira.drop import clean_name

CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # all but tab and newline


class CliError(Exception):
    pass


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "ira" / "client.json"


def saved() -> dict[str, Any]:
    try:
        data = json.loads(config_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(values: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as out:
        json.dump(values, out)
    path.chmod(0o600)


def make_client(url: str, token: str | None = None) -> httpx.Client:
    headers = {"User-Agent": f"ira-cli/{__version__}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=url, headers=headers, timeout=60.0)


def connect(args: argparse.Namespace) -> httpx.Client:
    stored = saved()
    url = args.url or os.environ.get("IRA_URL") or stored.get("url") or ""
    token = os.environ.get("IRA_TOKEN") or stored.get("token")
    if not url or not token:
        raise CliError("not signed in: run  ira drop login --url https://your-ira")
    return make_client(address(url), token)


def check(response: httpx.Response, *, signing_in: bool = False) -> httpx.Response:
    if response.is_success:
        return response
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if response.status_code == 401 and not signing_in:
        detail = "this token no longer works: sign in again with  ira drop login"
    elif response.status_code == 403 and not signing_in:
        detail = "this token cannot use Drop: make one that can with  ira drop login"
    if not isinstance(detail, str):
        detail = f"Ira answered {response.status_code}"
    raise CliError(detail)


def handled(command: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    @functools.wraps(command)
    def run(args: argparse.Namespace) -> int:
        try:
            return command(args)
        except CliError as exc:
            print(f"ira drop: {exc}", file=sys.stderr)
        except httpx.HTTPError as exc:
            print(f"ira drop: could not reach Ira ({type(exc).__name__})", file=sys.stderr)
        return 1

    return run


def printable(text: str) -> str:
    return CONTROL.sub("", text)


def size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def line(item: dict[str, Any]) -> str:
    """One item on one line: its id, when, where from, and what."""
    when = dt.datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
    what = " ".join(printable(item.get("text") or "").split())
    if item["kind"] == "file":
        name = " ".join(printable(item["name"] or "").split())
        what = f"{name} ({size(item['size'] or 0)})" + (f"  {what}" if what else "")
    if len(what) > 100:
        what = what[:99] + "…"
    source = printable(item.get("from_label") or "")[:12]
    return f"{item['id']:>6}  {when.astimezone():%d %b %H:%M}  {source:<12}  {what}"


def free(path: Path) -> Path:
    """``plan.pdf``, else ``plan (1).pdf``, ``plan (2).pdf``: never over a file that is there."""
    n = 1
    found = path
    while found.exists():
        found = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return found


def address(url: str) -> str:
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise CliError("use Ira's https:// address (http only for this computer)")
    return url


@handled
def cmd_login(args: argparse.Namespace) -> int:
    before = saved()
    url = address(
        args.url
        or os.environ.get("IRA_URL")
        or before.get("url")
        or input("Ira's address (https://...): ")
    )
    email = args.email or input("Email: ").strip()
    password = getpass.getpass("Password: ")
    pin = getpass.getpass("PIN: ")
    with make_client(url) as client:
        body = {"email": email, "password": password, "use_cookie": False}
        session = check(client.post("/v1/auth/login", json=body), signing_in=True).json()
        signed_in = {"Authorization": f"Bearer {session['session_token']}"}
        try:
            request = {"label": args.label, "pin": pin, "drop": True}
            made = check(
                client.post("/v1/me/tokens", json=request, headers=signed_in), signing_in=True
            ).json()
            if before.get("url") == url and before.get("token_id"):
                # The token this computer had before: no use now, so it stops.
                client.delete(f"/v1/me/tokens/{before['token_id']}", headers=signed_in)
        finally:
            client.post("/v1/auth/logout", headers=signed_in)
    save({"url": url, "token": made["token"], "token_id": made["id"]})
    print(f"Signed in to {url}. The token is in {config_path()}, readable by you alone.")
    return 0


@handled
def cmd_send(args: argparse.Namespace) -> int:
    if (args.text is None) == (args.path is None):
        raise CliError("send a file, - for stdin, or --text")
    caption = {"text": args.caption} if args.caption else None
    with connect(args) as client:
        if args.text is not None:
            response = client.post("/v1/me/drop", json={"text": args.text})
        elif args.path == "-":
            data = sys.stdin.buffer.read()
            try:
                text = None if args.name else data.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text is not None and "\x00" not in text:
                response = client.post("/v1/me/drop", json={"text": text})
            else:
                files = {"file": (args.name or "stdin", data)}
                response = client.post("/v1/me/drop", files=files, data=caption)
        else:
            path = Path(args.path)
            if not path.is_file():
                raise CliError(f"{args.path}: no such file")
            with path.open("rb") as source:
                files = {"file": (args.name or path.name, source)}
                response = client.post("/v1/me/drop", files=files, data=caption)
        item = check(response).json()
    print(f"Sent. {line(item)}")
    return 0


@handled
def cmd_list(args: argparse.Namespace) -> int:
    with connect(args) as client:
        listed = check(client.get("/v1/me/drop", params={"limit": args.limit})).json()
    if args.json:
        print(json.dumps(listed, indent=2, ensure_ascii=False))
    elif not listed["items"]:
        print("Your Drop is empty.")
    else:
        for item in listed["items"]:
            print(line(item))
        if listed["has_more"]:
            print(f"More with  ira drop list --limit {min(args.limit * 2, 200)}")
    return 0


@handled
def cmd_get(args: argparse.Namespace) -> int:
    with connect(args) as client:
        item = check(client.get(f"/v1/me/drop/{args.id}")).json()
        if item["kind"] != "file":
            text = item.get("text") or ""
            print(printable(text) if sys.stdout.isatty() else text)
            return 0
        to_stdout = args.output == "-"
        name = clean_name(item["name"])
        if to_stdout:
            target = None
        elif args.output:
            target = Path(args.output)
            target = free(target / name) if target.is_dir() else target
        else:
            target = free(Path(name))
        partial = target.with_name(target.name + ".part") if target else None
        digest = hashlib.sha256()
        try:
            with client.stream("GET", f"/v1/me/drop/{args.id}/file") as response:
                if not response.is_success:
                    response.read()
                    check(response)
                out = partial.open("wb") if partial else sys.stdout.buffer
                try:
                    for chunk in response.iter_bytes():
                        out.write(chunk)
                        digest.update(chunk)
                finally:
                    if partial:
                        out.close()
            if item.get("sha256") and digest.hexdigest() != item["sha256"]:
                raise CliError("the download does not match the file: try again")
        except BaseException:
            if partial:
                partial.unlink(missing_ok=True)
            raise
    if partial and target:
        partial.replace(target)
        print(f"Saved {target} ({size(item['size'] or 0)})")
    return 0


@handled
def cmd_rm(args: argparse.Namespace) -> int:
    with connect(args) as client:
        check(client.delete(f"/v1/me/drop/{args.id}"))
    print(f"Deleted {args.id} from every device.")
    return 0


def add_commands(drop: Any, add: Callable[..., argparse.ArgumentParser]) -> None:
    def command(name: str, handler: Callable[[argparse.Namespace], int], help: str):
        p = add(name, handler, help, drop)
        p.add_argument("--url", help="Ira's address (default: $IRA_URL, else what login saved)")
        return p

    p = command("login", cmd_login, "sign in once with your email, password and PIN")
    p.add_argument("--email")
    p.add_argument("--label", default="ira CLI", help='the token\'s name (default: "ira CLI")')
    p = command("send", cmd_send, "send a file, - for stdin, or --text")
    p.add_argument("path", nargs="?", help="a file, or - for what comes in on stdin")
    p.add_argument("--text", help="text or a link, instead of a file")
    p.add_argument("--caption", help="a few words with the file")
    p.add_argument("--name", help="the file's name (stdin is then sent as a file)")
    p = command("list", cmd_list, "what is in your Drop, newest first")
    p.add_argument("--limit", type=int, default=20, choices=range(1, 201), metavar="1-200")
    p.add_argument("--json", action="store_true", help="the items as JSON")
    p = command("get", cmd_get, "save a file from your Drop, or print its text")
    p.add_argument("id", type=int)
    p.add_argument("-o", "--output", help="a file or folder, or - for stdout (default: here)")
    p = command("rm", cmd_rm, "delete an item from every device")
    p.add_argument("id", type=int)
