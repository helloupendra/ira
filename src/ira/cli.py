"""The ``ira`` command line.

ira setup                         create the owner account
ira serve                         run the API, web chat and enabled channels
ira pin set [--user E]            set a user's action PIN (default: the first owner)
ira user add --email E --role R   add an admin, staff or viewer account
ira user list
ira token create --label phone    create an API token (shown once)
ira token list | revoke ID|LABEL
ira telegram pair                 print a one-time pairing code
ira demo seed                     create demo data for the configured tools
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from collections.abc import Callable

from ira import __version__
from ira.accounts import ROLES, TOKEN_SCOPES, AccountError, Accounts, User, parse_scopes
from ira.config import ConfigError, Settings, load_settings
from ira.security import valid_pin
from ira.store import Store


def _settings(args: argparse.Namespace) -> Settings:
    return load_settings(args.config)


def _store(settings: Settings) -> Store:
    return Store(settings.db_path)


def _secret_input(prompt: str, *, confirm: bool) -> str:
    """Read a secret from the terminal, or one line from stdin when piped."""
    if not sys.stdin.isatty():
        return sys.stdin.readline().strip()
    first = getpass.getpass(prompt)
    if confirm and getpass.getpass("Again: ") != first:
        raise SystemExit("The two entries did not match.")
    return first


def _pick_user(accounts: Accounts, email: str | None) -> User:
    if email:
        user = accounts.find_user(email)
        if user is None:
            raise SystemExit(f"No user with email {email}.")
        return user
    owners = [u for u in accounts.users() if u.role == "owner"]
    if not owners:
        raise SystemExit("No owner account yet. Run `ira setup` first.")
    return owners[0]


def cmd_setup(args: argparse.Namespace) -> int:
    settings = _settings(args)
    accounts = Accounts(_store(settings))
    if accounts.count() > 0:
        print("Setup is already done. Sign in with your existing account.")
        return 1
    email = args.email or input("Owner email: ").strip()
    password = _secret_input("Password (10+ characters): ", confirm=True)
    try:
        user = accounts.create_first_owner(email, password)
    except AccountError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Created owner {user.email}. Next: `ira pin set`, then `ira serve`.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from ira.channels.http import create_app
    from ira.runtime import build_runtime

    settings = _settings(args)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    runtime = build_runtime(settings)
    host = args.host or settings.channels.http.host
    port = args.port or settings.channels.http.port
    print(f"{runtime.assistant.name} is listening on http://{host}:{port}  (API docs: /v1/docs)")
    uvicorn.run(create_app(runtime), host=host, port=port, log_level="info")
    return 0


def cmd_pin_set(args: argparse.Namespace) -> int:
    from ira.tools.actions import ActionGuard
    from ira.tools.registry import ToolRegistry

    settings = _settings(args)
    store = _store(settings)
    user = _pick_user(Accounts(store), args.user)
    pin = _secret_input(f"New action PIN for {user.email} (4-12 digits): ", confirm=True)
    if not valid_pin(pin):
        print("Error: the PIN must be 4 to 12 digits.", file=sys.stderr)
        return 1
    # Run on the server itself, so it also lifts a wrong-PIN lock.
    ActionGuard(store, ToolRegistry()).set_pin(
        pin, user_id=user.id, actor=f"{user.email} via cli", channel="cli", unlock=True
    )
    print(f"Action PIN set for {user.email}. Wrong PINs lock actions after 3 tries.")
    return 0


def cmd_token_create(args: argparse.Namespace) -> int:
    settings = _settings(args)
    accounts = Accounts(_store(settings))
    user = _pick_user(accounts, args.user)
    try:
        token, token_id = accounts.create_token(user, args.label, parse_scopes(args.scope))
    except AccountError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Token {token_id} for {user.email} (label '{args.label}', scope {args.scope}).")
    print("It is shown once. Store it somewhere safe:\n")
    print(token)
    return 0


def cmd_token_list(args: argparse.Namespace) -> int:
    settings = _settings(args)
    rows = Accounts(_store(settings)).tokens()
    if not rows:
        print("No tokens.")
    for row in rows:
        state = "revoked" if row["revoked_at"] else "active"
        print(f"{row['id']}  {row['label']:<16} {row['scopes']:<28} {row['email']:<28} {state}")
    return 0


def cmd_token_revoke(args: argparse.Namespace) -> int:
    settings = _settings(args)
    count = Accounts(_store(settings)).revoke_token(args.token)
    print(f"Revoked {count} token(s).")
    return 0 if count else 1


def cmd_telegram_pair(args: argparse.Namespace) -> int:
    from ira.channels.telegram import PAIRING_SECONDS, create_pairing_code

    settings = _settings(args)
    store = _store(settings)
    user = _pick_user(Accounts(store), args.user)
    code = create_pairing_code(store, user.id)
    minutes = PAIRING_SECONDS // 60
    print(f"Send this to your bot within {minutes} minutes, from the chat to pair:\n")
    print(f"/pair {code}\n")
    print(f"The chat will act as {user.email} ({user.role}). The code works once.")
    return 0


def cmd_demo_seed(args: argparse.Namespace) -> int:
    from ira.tools.loader import load_tool_modules, run_seed
    from ira.tools.registry import ToolContext

    settings = _settings(args)
    if not settings.tools:
        print("No tool modules in the config; nothing to seed.")
        return 1
    ctx = ToolContext(data_dir=settings.data_dir, config_dir=settings.config_dir)
    modules = load_tool_modules(settings.tools, ctx)
    results = run_seed(modules, ctx)
    if not results:
        print("None of the tool modules defines seed(ctx).")
        return 1
    for name, result in results:
        print(f"{name}: {result}")
    return 0


def cmd_user_add(args: argparse.Namespace) -> int:
    settings = _settings(args)
    accounts = Accounts(_store(settings))
    if accounts.count() == 0:
        print("No owner account yet. Run `ira setup` first.", file=sys.stderr)
        return 1
    password = _secret_input("Password (10+ characters): ", confirm=True)
    try:
        user = accounts.create_user(args.email, password, args.role)
    except AccountError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Added {user.email} as {user.role}.")
    return 0


def cmd_user_list(args: argparse.Namespace) -> int:
    settings = _settings(args)
    for user in Accounts(_store(settings)).users():
        print(f"{user.id:>4}  {user.email:<32} {user.role}")
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    print(f"ira {__version__}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ira", description="Hey Ira: your own voice assistant.")
    parser.add_argument(
        "--config", "-c", help="path to ira.yaml (default: ./ira.yaml or $IRA_CONFIG)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler: Callable[[argparse.Namespace], int], help: str, parent=sub):
        p = parent.add_parser(name, help=help)
        # Accept --config after the subcommand too; SUPPRESS keeps an earlier value.
        p.add_argument("--config", "-c", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        p.set_defaults(handler=handler)
        return p

    p = add("setup", cmd_setup, "create the owner account")
    p.add_argument("--email")

    p = add("serve", cmd_serve, "run the API, web chat and enabled channels")
    p.add_argument("--host")
    p.add_argument("--port", type=int)

    pin = sub.add_parser("pin", help="manage the action PIN").add_subparsers(
        dest="pin_command", required=True
    )
    p = add("set", cmd_pin_set, "set or change a user's action PIN", pin)
    p.add_argument("--user", help="whose PIN (default: the first owner)")

    token = sub.add_parser("token", help="manage API tokens").add_subparsers(
        dest="token_command", required=True
    )
    p = add("create", cmd_token_create, "create a token (printed once)", token)
    p.add_argument("--label", required=True, help="what the token is for, e.g. phone")
    p.add_argument(
        "--scope",
        default="ask",
        help=f"comma-separated, from {', '.join(TOKEN_SCOPES)} (default: ask)",
    )
    p.add_argument("--user", help="owner of the token (default: the first owner)")
    add("list", cmd_token_list, "list tokens", token)
    p = add("revoke", cmd_token_revoke, "revoke a token by id or label", token)
    p.add_argument("token")

    telegram = sub.add_parser("telegram", help="Telegram channel").add_subparsers(
        dest="telegram_command", required=True
    )
    p = add("pair", cmd_telegram_pair, "print a one-time pairing code", telegram)
    p.add_argument("--user", help="the account the chat acts as (default: the first owner)")

    demo = sub.add_parser("demo", help="demo data").add_subparsers(
        dest="demo_command", required=True
    )
    add("seed", cmd_demo_seed, "create demo data for the configured tool modules", demo)

    user = sub.add_parser("user", help="manage accounts").add_subparsers(
        dest="user_command", required=True
    )
    p = add("add", cmd_user_add, "add an account (password from the terminal)", user)
    p.add_argument("--email", required=True)
    p.add_argument("--role", required=True, choices=[r for r in ROLES if r != "owner"])
    add("list", cmd_user_list, "list accounts", user)

    add("version", cmd_version, "print the version")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
