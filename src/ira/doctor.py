"""``ira doctor``: check one business folder and say plainly what is wrong.

Each check prints one line: ``ok``, ``warn``, ``FAIL`` or ``skip``, and the
command exits non-zero when anything failed. It checks that:

* the config parses, and every model reference names a configured provider;
* the data folder is writable by the user running the check;
* the port is free, or is held by this IRA instance;
* each tool module imports and registers its tools;
* each model in each chain answers a tiny prompt (ok and latency);
* speech-to-text and text-to-speech each do one tiny round trip;
* an owner account exists and has an action PIN;
* ``public_url`` is set when the instance is meant to be public.

``--no-models`` skips the model and voice calls, so nothing leaves the machine.
The port check may ask ``127.0.0.1`` who is listening; that is all.

Doctor never creates the database or the data folder: run as the wrong user
(root, say), it would leave files the service cannot write. It reads
``ira.db`` read-only, and refuses to run as root on a folder someone else owns.
"""

from __future__ import annotations

import asyncio
import errno
import os
import socket
import sqlite3
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ira.config import ConfigError, Settings, load_settings
from ira.models.base import ChatProvider, ProviderError
from ira.models.gateway import Gateway, split_ref
from ira.models.http import HttpClient

Status = Literal["ok", "warn", "fail", "skip"]
LOOPBACK = ("127.0.0.1", "::1", "localhost")
SPOKEN_TEST = "Ready."


@dataclass
class Check:
    status: Status
    what: str
    detail: str


@dataclass(frozen=True)
class PortState:
    """Who holds a port: nobody, an IRA (with its public status), or something else."""

    state: Literal["free", "ira", "other", "unavailable"]
    name: str | None = None
    version: str | None = None
    setup_required: bool | None = None
    error: str | None = None


@dataclass
class DoctorOptions:
    models: bool = True  # call each model, STT and TTS once
    public: bool = False  # the instance is meant to be reached by others
    timeout: float = 30.0  # seconds per model or voice call


@dataclass
class Report:
    config: Path | None
    checks: list[Check] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail")

    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if c.status == "warn")

    def add(self, status: Status, what: str, detail: str) -> Check:
        check = Check(status, what, detail)
        self.checks.append(check)
        return check

    def text(self) -> str:
        width = max((len(c.what) for c in self.checks), default=0)
        lines = [f"IRA doctor: {self.config or '(no ira.yaml: defaults)'}", ""]
        for check in self.checks:
            label = "FAIL" if check.status == "fail" else check.status
            lines.append(f"  {label:<5} {check.what:<{width}}  {check.detail}")
        verdict = "All good." if not self.failed else f"{self.failed} failed."
        if self.warnings:
            verdict += f" {self.warnings} warning{'s' if self.warnings != 1 else ''}."
        lines += ["", verdict]
        return "\n".join(lines)


def _short(text: str, limit: int = 200) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, ProviderError):
        return _short(f"{exc.kind}: {exc}")
    return _short(f"{type(exc).__name__}: {exc}")


# --- who runs the check ----------------------------------------------------------------


def _owner_uid(path: Path) -> int | None:
    try:
        return path.stat().st_uid
    except OSError:
        return None


def check_user(report: Report, folder: Path) -> bool:
    """False when doctor must not go on: root, on a folder that belongs to someone else."""
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() != 0:
        return True
    owner = _owner_uid(folder)
    if owner not in (None, 0):
        report.add(
            "fail",
            "user",
            f"running as root, but {folder} belongs to uid {owner}. Run doctor as that user "
            f"(sudo -u <user> ira doctor {folder}), so it cannot leave files the service "
            "cannot write.",
        )
        return False
    report.add("warn", "user", "running as root; run IRA itself as an unprivileged user")
    return True


# --- config ----------------------------------------------------------------------------


def check_config(report: Report, config: Path | None) -> Settings | None:
    try:
        settings = load_settings(config)
    except ConfigError as exc:
        report.add("fail", "config", _short(str(exc), 600))
        return None
    problems = []
    providers = settings.models.providers
    for tier, refs in settings.models.tiers.items():
        if not refs:
            problems.append(f"tier '{tier}' has no models")
        for ref in refs:
            try:
                provider, _ = split_ref(ref)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if provider not in providers:
                problems.append(f"tier '{tier}' uses unknown provider '{provider}'")
    if settings.assistant.tier not in settings.models.tiers:
        problems.append(f"assistant.tier '{settings.assistant.tier}' is not a tier")
    voice = settings.voice
    for kind, cfg, needs in (
        ("stt", voice.stt, voice.stt.type in ("chat_audio", "whisper")),
        ("tts", voice.tts, voice.tts.type == "openai"),
    ):
        if needs and cfg.provider not in providers:
            problems.append(f"voice.{kind}.provider '{cfg.provider}' is not a provider")
    for problem in problems:
        report.add("fail", "config", problem)
    if not problems:
        what = f"{settings.assistant.name} for {settings.assistant.business}"
        report.add("ok", "config", f"parses: {_short(what, 80)}")
    return settings


# --- data folder -----------------------------------------------------------------------


# What Drop and connections need at runtime, by the name each installs as; an install older
# than these being in the base set may lack them.
NEEDED_PACKAGES = {
    "python-multipart": ("python_multipart", "multipart"),
    "cryptography": ("cryptography",),
}


def check_packages(report: Report) -> None:
    import importlib.util

    missing = [
        name
        for name, modules in NEEDED_PACKAGES.items()
        if not any(importlib.util.find_spec(module) for module in modules)
    ]
    if missing:
        report.add(
            "fail",
            "packages",
            f"{', '.join(missing)} missing (Drop needs them): pip install --upgrade ira-assistant",
        )
    else:
        report.add("ok", "packages", "everything Drop and connections need is installed")


def check_data_dir(report: Report, settings: Settings) -> None:
    data = settings.data_dir
    if not data.exists():
        parent = next((p for p in data.parents if p.exists()), None)
        if parent is not None and os.access(parent, os.W_OK | os.X_OK):
            report.add("ok", "data dir", f"{data} will be created on first start")
        else:
            report.add("fail", "data dir", f"{data} does not exist and cannot be created")
        return
    if not data.is_dir():
        report.add("fail", "data dir", f"{data} is not a folder")
        return
    try:
        with tempfile.NamedTemporaryFile(dir=data, prefix=".doctor-"):
            pass
    except OSError as exc:
        report.add("fail", "data dir", f"{data} is not writable: {exc.strerror or exc}")
        return
    stuck = [
        p.name
        for p in (settings.db_path, *(data / f"ira.db-{s}" for s in ("wal", "shm")))
        if p.exists() and not os.access(p, os.W_OK)
    ]
    if stuck:
        report.add(
            "fail", "data dir", f"{', '.join(stuck)} in {data} cannot be written by this user"
        )
        return
    report.add("ok", "data dir", f"{data} is writable")


# --- the database, read-only -----------------------------------------------------------


def _read_db(settings: Settings, sql: str, params: tuple = ()) -> list[sqlite3.Row] | None:
    """Rows from ira.db opened read-only, or None when there is no database yet."""
    if not settings.db_path.is_file():
        return None
    uri = f"{settings.db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _current_name(settings: Settings) -> str:
    """The assistant's name as the running server shows it (the console can rename it)."""
    from ira.assistant import NAME_SETTING

    try:
        rows = _read_db(settings, "SELECT value FROM settings WHERE key = ?", (NAME_SETTING,))
    except sqlite3.Error:
        rows = None
    return rows[0]["value"] if rows else settings.assistant.name


def check_owner(report: Report, settings: Settings) -> None:
    hint = (
        "open the one-time setup link `ira serve` prints (under systemd, in its journal), "
        "or run `ira setup`"
    )
    try:
        rows = _read_db(
            settings,
            "SELECT email, pin_hash IS NOT NULL AS has_pin FROM users "
            "WHERE role = 'owner' AND disabled_at IS NULL ORDER BY id",
        )
    except sqlite3.Error as exc:
        report.add("fail", "owner", f"cannot read {settings.db_path}: {exc}")
        return
    if rows is None:
        report.add("fail", "owner", f"no database yet: {hint}")
        return
    if not rows:
        report.add("fail", "owner", f"no owner account yet: {hint}")
        return
    with_pin = [r["email"] for r in rows if r["has_pin"]]
    if not with_pin:
        report.add(
            "fail",
            "owner",
            f"{rows[0]['email']} has no action PIN yet: set it in the app's menu "
            "or with `ira pin set`",
        )
        return
    others = f" (and {len(rows) - 1} more owner{'s' if len(rows) > 2 else ''})" if rows[1:] else ""
    report.add("ok", "owner", f"{with_pin[0]} has an action PIN{others}")


# --- port ------------------------------------------------------------------------------


def identify(host: str, port: int, timeout: float = 3.0) -> PortState:
    """Ask whoever holds the port for IRA's public status page."""
    import httpx

    shown = {"0.0.0.0": "127.0.0.1", "::": "::1", "": "127.0.0.1"}.get(host, host)
    if ":" in shown:
        shown = f"[{shown}]"
    try:
        response = httpx.get(f"http://{shown}:{port}/v1/auth/status", timeout=timeout)
        data = response.json()
        return PortState(
            "ira",
            name=str(data["name"]),
            version=str(data["version"]),
            setup_required=bool(data["setup_required"]),
        )
    except Exception:
        return PortState("other")


def probe_port(
    host: str, port: int, *, identify: Callable[[str, int], PortState] = identify
) -> PortState:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        # As uvicorn does: a port with only old TIME_WAIT connections counts as free.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                return PortState("unavailable", error=exc.strerror or str(exc))
        else:
            return PortState("free")
    return identify(host, port)


def check_port(
    report: Report,
    settings: Settings,
    probe: Callable[[str, int], PortState] = probe_port,
) -> None:
    host, port = settings.channels.http.host, settings.channels.http.port
    where = f"{host}:{port}"
    state = probe(host, port)
    if state.state == "free":
        report.add("ok", "port", f"{where} is free")
    elif state.state == "unavailable":
        report.add("fail", "port", f"cannot listen on {where}: {state.error}")
    elif state.state == "other":
        report.add("fail", "port", f"{where} is in use by a program that is not IRA")
    else:
        expected = _current_name(settings)
        try:
            owners = _read_db(settings, "SELECT 1 FROM users LIMIT 1")
        except sqlite3.Error:
            owners = None
        ours_has_owner = bool(owners)
        same = state.name == expected and not (ours_has_owner and state.setup_required)
        running = f"IRA {state.version} named '{state.name}'"
        if same:
            report.add("ok", "port", f"{where} is held by this instance ({running})")
        else:
            report.add(
                "warn",
                "port",
                f"{where} is held by {running}, which does not look like this folder's "
                "instance; give each business its own port",
            )


# --- tools -----------------------------------------------------------------------------


def check_tools(report: Report, settings: Settings) -> None:
    from ira.tools.loader import import_tool_module
    from ira.tools.registry import ToolContext, default_registry

    if not settings.tools:
        report.add(
            "warn",
            "tools",
            "no tool modules: only each person's paired devices and search add tools",
        )
        return
    ctx = ToolContext(data_dir=settings.data_dir, config_dir=settings.config_dir)
    loaded: set[str] = set()
    for spec in settings.tools:
        try:
            module = import_tool_module(spec, settings.config_dir)
            hook = getattr(module, "setup", None)
            if callable(hook):
                hook(ctx)
            tools = [t for t in default_registry if t.fn.__module__ == module.__name__]
            for tool in tools:
                tool.schema()  # the schema the model sees must build
        except Exception as exc:
            report.add("fail", "tools", f"{spec}: {_error_text(exc)}")
            continue
        if not tools:
            report.add("warn", "tools", f"{spec}: imports, but registers no tools")
            continue
        loaded.update(t.name for t in tools)
        names = ", ".join(f"{t.name} ({t.kind})" for t in tools)
        report.add("ok", "tools", f"{spec}: {names}")
    for name in settings.actions.tools:
        tool = default_registry.get(name)
        if tool is None or tool.kind != "action":
            report.add("warn", "tools", f"actions.tools names '{name}', not an action tool")


# --- models and voice ------------------------------------------------------------------


def _build_providers(
    settings: Settings,
) -> tuple[dict[str, ChatProvider], dict[str, HttpClient], dict[str, str]]:
    """Providers that tiers or voice use, their HTTP clients, and why any failed to build."""
    from ira.runtime import build_http, build_provider

    used = {ref.partition(":")[0] for refs in settings.models.tiers.values() for ref in refs}
    used |= {settings.voice.stt.provider, settings.voice.tts.provider} - {None}
    providers: dict[str, ChatProvider] = {}
    https: dict[str, HttpClient] = {}
    broken: dict[str, str] = {}
    for name, cfg in settings.models.providers.items():
        if name not in used:
            continue
        try:
            http = build_http(name, cfg) if cfg.type != "fake" else None
            providers[name] = build_provider(name, cfg, http)
        except Exception as exc:
            broken[name] = _error_text(exc)
            continue
        if http is not None:
            https[name] = http
    return providers, https, broken


async def _check_models(
    report: Report,
    settings: Settings,
    options: DoctorOptions,
    providers: dict[str, ChatProvider],
    broken: dict[str, str],
) -> None:
    tiers = settings.models.tiers
    gateway = Gateway(
        providers, {}, timeout_seconds=options.timeout, max_tokens=settings.models.max_tokens
    )

    async def probe(ref: str) -> tuple[str, Status, str]:
        provider = ref.partition(":")[0]
        if provider in broken:
            return ref, "fail", broken[provider]
        if provider not in providers:
            return ref, "fail", f"provider '{provider}' is not configured"
        try:
            response, error, seconds = await gateway.probe(ref)
        except Exception as exc:  # a provider bug must not hide the other results
            return ref, "fail", _error_text(exc)
        if error is not None:
            return ref, "fail", _error_text(error)
        return ref, "ok", f"answered in {seconds:.2f} s"

    refs = list(dict.fromkeys(ref for chain in tiers.values() for ref in chain))
    answers = await asyncio.gather(*(probe(ref) for ref in refs))
    results = {ref: (status, detail) for ref, status, detail in answers}
    for tier, chain in tiers.items():
        for index, ref in enumerate(chain, 1):
            status, detail = results[ref]
            report.add(status, f"model {tier} {index}/{len(chain)}", f"{ref}  {detail}")


def silence_wav(seconds: float = 1.0, rate: int = 16_000) -> bytes:
    from ira.voice.audio import pcm16_wav

    return pcm16_wav(bytes(2 * int(rate * seconds)), rate)


async def _timed(coro: Any, timeout: float) -> tuple[Any, float]:
    started = time.monotonic()
    result = await asyncio.wait_for(coro, timeout=timeout)
    return result, time.monotonic() - started


async def _check_voice(
    report: Report,
    settings: Settings,
    options: DoctorOptions,
    https: dict[str, HttpClient],
    stt: Any,
    tts: Any,
) -> None:
    from ira.runtime import build_stt, build_tts

    stt_cfg, tts_cfg = settings.voice.stt, settings.voice.tts
    if stt_cfg.type == "none":
        report.add("skip", "speech-to-text", "not configured")
    else:
        what = f"{stt_cfg.type} {stt_cfg.model or ''}".strip()
        if stt_cfg.type == "transcribe":
            what = f"transcribe {', '.join(stt_cfg.languages)} ({stt_cfg.region})"
        try:
            engine = stt if stt is not None else build_stt(settings, https)
            heard, seconds = await _timed(engine.transcribe(silence_wav()), options.timeout)
            shown = f'heard "{_short(heard, 40)}"' if heard else "heard nothing, as expected"
            report.add("ok", "speech-to-text", f"{what}  {seconds:.2f} s, 1 s of silence: {shown}")
        except TimeoutError:
            report.add("fail", "speech-to-text", f"{what}  no answer in {options.timeout:.0f} s")
        except Exception as exc:
            report.add("fail", "speech-to-text", f"{what}  {_error_text(exc)}")
    if tts_cfg.type == "none":
        report.add(
            "skip", "text-to-speech", "not configured: the web app speaks with the browser's voice"
        )
        return
    what = f"{tts_cfg.type} {tts_cfg.voice or ''}".strip()
    if tts_cfg.type == "polly":
        what += f" ({tts_cfg.engine}, {tts_cfg.region})"
    try:
        engine = tts if tts is not None else build_tts(settings, https)
        audio, seconds = await _timed(engine.speak(SPOKEN_TEST), options.timeout)
        if not audio:
            report.add("fail", "text-to-speech", f"{what}  answered with no audio")
        else:
            report.add("ok", "text-to-speech", f"{what}  {seconds:.2f} s, {len(audio):,} bytes")
    except TimeoutError:
        report.add("fail", "text-to-speech", f"{what}  no answer in {options.timeout:.0f} s")
    except Exception as exc:
        report.add("fail", "text-to-speech", f"{what}  {_error_text(exc)}")


async def _check_calls(
    report: Report,
    settings: Settings,
    options: DoctorOptions,
    providers: dict[str, ChatProvider] | None,
    stt: Any,
    tts: Any,
) -> None:
    https: dict[str, HttpClient] = {}
    broken: dict[str, str] = {}
    if providers is None:
        providers, https, broken = _build_providers(settings)
    try:
        await _check_models(report, settings, options, providers, broken)
        await _check_voice(report, settings, options, https, stt, tts)
    finally:
        for client in https.values():
            await client.aclose()


# --- public address --------------------------------------------------------------------


def check_public_url(report: Report, settings: Settings, options: DoctorOptions) -> None:
    http = settings.channels.http
    public = options.public or http.host not in LOOPBACK
    if http.public_url:
        if http.public_url.startswith("http://") and not any(
            http.public_url.startswith(f"http://{h}") for h in LOOPBACK
        ):
            report.add(
                "warn", "public url", f"{http.public_url}: browsers allow the mic on https only"
            )
        else:
            report.add("ok", "public url", f"links point at {http.public_url}")
    elif public:
        why = "--public" if options.public else f"it listens on {http.host}"
        report.add(
            "fail",
            "public url",
            f"not set, but this instance is public ({why}): set channels.http.public_url "
            "or IRA_PUBLIC_URL to the address people open",
        )
    else:
        report.add("skip", "public url", "not set; fine while only this machine uses it")


# --- all together ----------------------------------------------------------------------


def run(
    config: Path | None,
    options: DoctorOptions | None = None,
    *,
    providers: dict[str, ChatProvider] | None = None,
    stt: Any = None,
    tts: Any = None,
    port_probe: Callable[[str, int], PortState] | None = None,
) -> Report:
    """Run every check. Tests pass fake providers, voice and port probe."""
    options = options or DoctorOptions()
    report = Report(config)
    folder = config.parent if config else Path.cwd()
    if not check_user(report, folder):
        return report
    settings = check_config(report, config)
    if settings is None:
        return report
    check_packages(report)
    check_data_dir(report, settings)
    check_port(report, settings, port_probe or probe_port)
    check_tools(report, settings)
    if options.models:
        asyncio.run(_check_calls(report, settings, options, providers, stt, tts))
    else:
        count = sum(len(chain) for chain in settings.models.tiers.values())
        report.add(
            "skip", "models", f"{count} model{'s' if count != 1 else ''} not called (--no-models)"
        )
        report.add("skip", "voice", "speech-to-text and text-to-speech not called (--no-models)")
    check_owner(report, settings)
    check_public_url(report, settings, options)
    return report


def find_config(target: str | None, explicit: str | None) -> Path | None:
    """``ira doctor FOLDER`` or ``ira --config FILE doctor``; else ./ira.yaml or $IRA_CONFIG."""
    from ira.config import find_config as find

    if target:
        path = Path(target).expanduser()
        path = path / "ira.yaml" if path.is_dir() else path
        if not path.is_file():
            raise ConfigError(f"no ira.yaml at {path}")
        return path.resolve()
    found = find(explicit)
    return found.resolve() if found else None


def main(target: str | None, explicit: str | None, options: DoctorOptions) -> int:
    try:
        config = find_config(target, explicit)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    report = run(config, options)
    print(report.text(), flush=True)
    return 1 if report.failed else 0
