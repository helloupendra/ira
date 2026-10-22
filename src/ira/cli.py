"""The ``ira`` command line.

ira init FOLDER [--provider P]    create a business (or --personal) folder: ira.yaml, README
ira doctor [FOLDER] [--no-models] check a business folder; non-zero exit on a failure
ira setup                         create the owner account
ira serve                         run the API, web chat, console and enabled channels
ira pin set [--user E]            set a user's action PIN (default: the first owner)
ira user add --email E --role R   add an admin, staff or viewer account
ira user list
ira token create --label phone    create an API token (shown once)
ira token list | revoke ID|LABEL
ira telegram pair                 print a one-time pairing code
ira demo seed                     create demo data for the configured tools
ira eval language [--spoken]      measure Hindi, English and Hinglish understanding
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
from ira.security import PIN_RULE, valid_pin
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
    from ira import setupcode

    settings = _settings(args)
    store = _store(settings)
    accounts = Accounts(store)
    if accounts.count() > 0:
        print("Setup is already done. Sign in with your existing account.")
        return 1
    if args.new_code:
        http = settings.channels.http
        code = setupcode.renew(store)
        print(setup_banner(code, http.host, http.port, http.public_url))
        print("    The earlier link no longer works.")
        return 0
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
    # The console reports what was bound, not what ira.yaml says.
    runtime.bound_host, runtime.bound_port = host, port
    # Flushed: under a service manager stdout is a pipe, and the setup code must show.
    print(
        f"{runtime.assistant.name} is listening on http://{host}:{port}  (API docs: /v1/docs)",
        flush=True,
    )
    if runtime.public_url:
        print(f"People open it at {runtime.public_url}", flush=True)
    code = runtime.ensure_setup_code()
    if code:
        print(setup_banner(code, host, port, runtime.public_url), flush=True)
        runtime.setup_code_shown = True
    from ira.devices.protocol import MAX_FRAME_BYTES

    uvicorn.run(
        create_app(runtime),
        host=host,
        port=port,
        log_level="info",
        # Device frames are 1 MB at most; the WebSocket refuses bigger ones before reading them.
        ws_max_size=MAX_FRAME_BYTES + 1024,
    )
    return 0


def setup_banner(code: str, host: str, port: int, public_url: str | None = None) -> str:
    """What `ira serve` prints while no account exists, so the owner can claim it."""
    from ira.runtime import local_url
    from ira.web import setup_page

    base = public_url or local_url(host, port)
    page = setup_page()
    # The code rides in the fragment, which the browser never sends to a server or proxy log.
    return (
        "\n    No account exists yet. To create the owner account, open:\n\n"
        f"        {base}{page}#code={code}\n\n"
        f"    or enter the setup code {code} on that page. It works once, for 24\n"
        "    hours, and a restart keeps it. `ira setup --new-code` replaces it;\n"
        "    `ira setup` in a terminal creates the owner here instead.\n"
    )


def cmd_pin_set(args: argparse.Namespace) -> int:
    from ira.tools.actions import ActionGuard
    from ira.tools.registry import ToolRegistry

    settings = _settings(args)
    store = _store(settings)
    user = _pick_user(Accounts(store), args.user)
    pin = _secret_input(f"New action PIN for {user.email} ({PIN_RULE}): ", confirm=True)
    if not valid_pin(pin):
        print(f"Error: the PIN must be {PIN_RULE}.", file=sys.stderr)
        return 1
    # Run on the server itself, so it also lifts a wrong-PIN lock.
    ActionGuard(store, ToolRegistry()).set_pin(
        pin, user_id=user.id, actor=user.email, channel="cli", unlock=True
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


def cmd_user_password(args: argparse.Namespace) -> int:
    from ira import changes

    settings = _settings(args)
    store = _store(settings)
    accounts = Accounts(store)
    user = accounts.find_user(args.email)
    if user is None:
        print(f"No account {args.email}.", file=sys.stderr)
        return 1
    password = _secret_input("New password (10+ characters): ", confirm=True)
    try:
        ended = accounts.set_password(user.id, password)
    except AccountError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    changes.record(
        store,
        "cli",
        "user.password_reset",
        user.email,
        channel="cli",
        after={"sessions_ended": ended},
    )
    print(f"Changed the password of {user.email}; {ended} session(s) signed out.")
    return 0


def cmd_user_email(args: argparse.Namespace) -> int:
    from ira import changes

    settings = _settings(args)
    store = _store(settings)
    accounts = Accounts(store)
    user = accounts.find_user(args.email)
    if user is None:
        print(f"No account {args.email}.", file=sys.stderr)
        return 1
    try:
        updated, before = accounts.set_email(user.id, args.new_email)
    except AccountError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if updated.email != before:
        changes.record(
            store,
            "cli",
            "user.email",
            updated.email,
            channel="cli",
            before=before,
            after=updated.email,
        )
    print(f"{before} now signs in as {updated.email}.")
    return 0


def cmd_device_code(args: argparse.Namespace) -> int:
    """A pairing code that lasts days, for someone far away (an app store's reviewers)."""
    from ira import changes
    from ira.devices.store import DeviceError, Devices
    from ira.runtime import local_url

    settings = _settings(args)
    store = _store(settings)
    user = Accounts(store).find_user(args.email)
    if user is None:
        print(f"No account {args.email}. Add one first: ira user add", file=sys.stderr)
        return 1
    skills = [s.strip() for s in (args.skills or "").split(",") if s.strip()]
    try:
        code, pairing = Devices(store).start_pairing(
            user.id, args.kind, args.label, skills, seconds=args.days * 86400, uses=args.uses
        )
    except DeviceError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    changes.record(
        store,
        "cli",
        "device.long_pairing",
        user.email,
        channel="cli",
        after={"kind": args.kind, "days": args.days, "uses": args.uses},
    )
    http = settings.channels.http
    base = (http.public_url or local_url(http.host, http.port)).rstrip("/")
    print(f"Pairing code for {user.email} ({args.kind}): {code[:4]}-{code[4:]}")
    print(f"Or the link: {base}/pair#code={code[:4]}-{code[4:]}")
    skills_on = ", ".join(pairing.skills) or "none"
    print(f"It works for {args.days} days, for {args.uses} device(s). Skills on: {skills_on}.")
    return 0


def cmd_user_list(args: argparse.Namespace) -> int:
    settings = _settings(args)
    for user in Accounts(_store(settings)).users():
        print(f"{user.id:>4}  {user.email:<32} {user.role}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    from pathlib import Path

    from ira.scaffold import InitError, InitOptions, init_folder

    options = InitOptions(
        name=args.name,
        business=args.business,
        port=args.port,
        provider=args.provider,
        region=args.region,
        voice=args.voice,
        public_url=args.public_url,
        personal=args.personal,
    )
    folder = Path(args.folder).expanduser()
    try:
        written = init_folder(folder, options)
    except (InitError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    where = folder.resolve()
    print(f"Created {where}:")
    for path in written:
        print(f"    {path.name}")
    print(
        "\nNext:\n"
        f"    cd {where}\n"
        "    ira doctor --no-models   check the config, tools and port (no calls)\n"
        "    ira serve                prints a one-time link to create the owner account\n"
        "    ira doctor               once the owner has a PIN: everything, models included"
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from ira.doctor import DoctorOptions
    from ira.doctor import main as doctor

    options = DoctorOptions(models=not args.no_models, public=args.public, timeout=args.timeout)
    return doctor(args.folder, args.config, options)


def cmd_eval_language(args: argparse.Namespace) -> int:
    from ira.evals.language import main as evaluate

    return evaluate(
        _settings(args), spoken=args.spoken, only=args.only, as_json=args.json, voice=args.voice
    )


def cmd_eval_live(args: argparse.Namespace) -> int:
    from ira.evals.live import main as evaluate

    return evaluate(
        _settings(args),
        hangover=args.hangover,
        only=args.only,
        as_json=args.json,
        transcribe_region=args.transcribe,
        limit=args.limit,
        tier=args.tier,
    )


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

    p = add("init", cmd_init, "create a business folder: ira.yaml, tools.py and a README")
    p.add_argument("folder", help="a new or empty folder")
    p.add_argument("--name", default="Ira", help="the assistant's name (default: Ira)")
    p.add_argument(
        "--business", default="your business", help='one line, e.g. "Sunrise Dental, a clinic"'
    )
    p.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default: 8765)")
    p.add_argument(
        "--provider",
        choices=["demo", "bedrock"],
        default="demo",
        help="demo: no key, no network (default); bedrock: Amazon Bedrock and Polly",
    )
    p.add_argument("--region", help="Bedrock Mantle region (default: us-east-1)")
    p.add_argument("--voice", help="Polly voice (default: Kajal, Indian English)")
    p.add_argument("--public-url", help="the address people open, e.g. https://ira.example.com")
    p.add_argument(
        "--personal",
        action="store_true",
        help="one person's own assistant: no placeholder tools, search settings",
    )

    p = add("doctor", cmd_doctor, "check a business folder: config, tools, models, voice, owner")
    p.add_argument("folder", nargs="?", help="the business folder (default: ./ira.yaml)")
    p.add_argument(
        "--no-models",
        action="store_true",
        help="do not call the models or the voice providers (nothing leaves this machine)",
    )
    p.add_argument(
        "--public", action="store_true", help="require public_url: people open it from elsewhere"
    )
    p.add_argument(
        "--timeout", type=float, default=30.0, help="seconds per model or voice call (default 30)"
    )

    p = add("setup", cmd_setup, "create the owner account")
    p.add_argument("--email")
    p.add_argument(
        "--new-code", action="store_true", help="replace the setup link instead (24 hours)"
    )

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
    device = sub.add_parser("device", help="devices").add_subparsers(
        dest="device_command", required=True
    )
    p = add("code", cmd_device_code, "a pairing code that lasts days (app reviewers)", device)
    p.add_argument("--email", required=True, help="the account the device will speak for")
    p.add_argument("--kind", choices=["android", "mac"], default="android")
    p.add_argument("--days", type=int, default=7, help="1 to 14 (default 7)")
    p.add_argument("--uses", type=int, default=3, help="devices it may pair (default 3)")
    p.add_argument("--label", help="the device's name (default: Android phone / Mac)")
    p.add_argument("--skills", help="skills to switch on, comma-separated")
    p = add("password", cmd_user_password, "set an account's password (signs it out)", user)
    p.add_argument("email")
    p = add("email", cmd_user_email, "change the email an account signs in with", user)
    p.add_argument("email")
    p.add_argument("new_email")

    evals = sub.add_parser("eval", help="evaluations against the configured models").add_subparsers(
        dest="eval_command", required=True
    )
    p = add("language", cmd_eval_language, "Hindi, English and Hinglish: intent, reply", evals)
    p.add_argument("--spoken", action="store_true", help="speak each request, then transcribe it")
    p.add_argument(
        "--voice",
        choices=["say", "polly"],
        help="who speaks for --spoken: macOS say, or Amazon Polly (default: say on macOS)",
    )
    p.add_argument("--only", choices=["hi", "hinglish", "en"], help="one language only")
    p.add_argument("--json", action="store_true", help="every result as JSON")
    p = add("live", cmd_eval_live, "real-time voice: end of speech to first word", evals)
    p.add_argument("--hangover", type=float, default=0.6, help="the app's quiet wait, seconds")
    p.add_argument("--only", choices=["hi", "hinglish", "en"], help="one language only")
    p.add_argument("--limit", type=int, help="at most this many requests")
    p.add_argument("--transcribe", metavar="REGION", help="use Transcribe in REGION for this run")
    p.add_argument("--tier", help="the model tier for the calls (default: voice.tier)")
    p.add_argument("--json", action="store_true", help="every result as JSON")

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
