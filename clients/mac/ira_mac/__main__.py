"""``python -m ira_mac``: run the daemon or the Chrome host, pair this Mac, or check on it.

pair     trade the pairing code from the Devices page for this Mac's token
run      the daemon (the LaunchAgent runs this)
host     the Chrome native-messaging host (Chrome runs this)
status   what is set up, never the token
unpair   tell the server goodbye and forget the token
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import json
import logging
import signal
import subprocess
import sys

from ira_mac import __version__, config, logs
from ira_mac.keychain import Keychain, KeychainError
from ira_mac.pair import PairError, choose, exchange

log = logging.getLogger("ira_mac")


def cmd_pair(args: argparse.Namespace) -> int:
    current = config.load()
    print("Make a pairing code on the Devices page of your Ira app (Add a device, Mac).")
    try:
        entry = getpass.getpass("Paste the pairing link, or type the code (hidden): ")
    except (EOFError, KeyboardInterrupt):
        print()
        return 1
    try:
        known = [args.server, config.given_server(), current.server]
        server, code = choose(entry, known, input)
        paired = exchange(server, code)
        Keychain().save(paired.token)
    except (PairError, KeychainError) as exc:
        print(f"Not paired: {exc}", file=sys.stderr)
        return 1
    config.save(config.Config(server=paired.server, device_id=paired.device_id, label=paired.label))
    skills = ", ".join(paired.skills) or "none yet (switch them on in the Devices page)"
    print(f"Paired as {paired.label} (device {paired.device_id}) with {paired.server}.")
    print(f"Skills on: {skills}. The token is in your Keychain under 'ira-mac'.")
    return 0


async def _run() -> int:
    from ira_mac.bridge import ChromeBridge
    from ira_mac.daemon import Daemon
    from ira_mac.routine import MacProbe, Routine
    from ira_mac.tools import Toolbox

    settings = config.load()
    if not settings.server:
        log.warning("not paired yet: run ./install.sh --pair; checking again in 5 minutes")
        await asyncio.sleep(300)  # then launchd starts it again
        return 0
    keychain = Keychain()
    bridge = ChromeBridge(config.socket_path())
    await bridge.start()
    announce: list = []
    toolbox = Toolbox(bridge, lambda *event: announce[0](*event))
    daemon = Daemon(settings.websocket_url(), keychain.load, toolbox, label=settings.label)
    announce.append(daemon.announce)
    routine = Routine(daemon.observe, MacProbe(), config.salt(settings))
    watcher = asyncio.create_task(routine.run(lambda: "routine" in daemon.skills))
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, daemon.stop)
    log.info("ira-mac %s starting for device %s", __version__, settings.device_id)
    try:
        await daemon.run_forever()
    finally:
        watcher.cancel()
        await toolbox.stop()
        await bridge.stop()
        log.info("ira-mac stopped")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    logs.setup(None if args.foreground else config.log_path())
    return asyncio.run(_run())


def cmd_host(args: argparse.Namespace) -> int:
    from ira_mac.host import main

    logs.setup(config.home() / "logs" / "chrome-host.log")
    return main(config.socket_path())


def cmd_status(args: argparse.Namespace) -> int:
    settings = config.load()
    token = Keychain().load()
    agent = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{_uid()}/{config.LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    info = {
        "version": __version__,
        "server": settings.server,
        "device_id": settings.device_id,
        "label": settings.label,
        "token_in_keychain": token is not None,
        "daemon_loaded": agent.returncode == 0,
        "chrome_socket": config.socket_path().exists(),
        "home": str(config.home()),
    }
    print(json.dumps(info, indent=2))
    return 0


def _uid() -> int:
    import os

    return os.getuid()


async def _goodbye(url: str, token: str) -> bool:
    from ira_mac.daemon import websocket_connect

    try:
        ws = await websocket_connect(url, token)
        await ws.send(json.dumps({"type": "bye"}))
        with contextlib.suppress(Exception):
            await asyncio.wait_for(ws.recv(), 5)  # the server closes the connection
        await ws.close()
        return True
    except Exception:
        return False


def cmd_unpair(args: argparse.Namespace) -> int:
    settings = config.load()
    keychain = Keychain()
    token = keychain.load()
    if token:
        told = bool(settings.server) and asyncio.run(_goodbye(settings.websocket_url(), token))
        print(
            "The server revoked this Mac."
            if told
            else "Could not reach the server: revoke this Mac on the Devices page too."
        )
        keychain.delete()
    settings.device_id = None
    config.save(settings)
    print("The token is gone from the Keychain.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ira-mac", description="The IRA Mac companion.")
    parser.add_argument("--version", action="version", version=f"ira-mac {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pair", help="pair this Mac with the code from the Devices page")
    p.add_argument("--server", help="the IRA server, e.g. https://ira.example.com")
    p.set_defaults(handler=cmd_pair)
    p = sub.add_parser("run", help="run the daemon")
    p.add_argument("--foreground", action="store_true", help="log to the terminal")
    p.set_defaults(handler=cmd_run)
    sub.add_parser("host", help="the Chrome native-messaging host").set_defaults(handler=cmd_host)
    sub.add_parser("status", help="what is set up").set_defaults(handler=cmd_status)
    sub.add_parser("unpair", help="forget this Mac's token").set_defaults(handler=cmd_unpair)
    # Chrome starts the host with the extension's origin as an argument; ignore extras.
    args, _ = parser.parse_known_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
