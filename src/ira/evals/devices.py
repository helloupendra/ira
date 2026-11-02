"""``ira eval devices``: from any device, does Ira reach the right device with the right tool?

Each request in ``devices.yaml`` goes through the real assistant loop, with its real prompts and
the configured models. The devices are stand-ins: they offer the tools their apps really offer
(``device_tools.json``, from each app's catalog) and answer with fixed, fictional results, so
nothing on a real device is touched. It uses a database in memory. Each request costs one to
three model calls.

A turn fails for the wrong tool or device, for running what must wait for a yes, for telling the
person to talk from another device, for a reason or a number that came from nowhere, and for
leaking a tool's internal words. Any change to prompts or tool descriptions is scored before and
after with this.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ira.config import Settings
from ira.devices.hub import Connection, ToolError
from ira.devices.protocol import DeviceTool

HERE = Path(__file__).resolve().parent
CASES = HERE / "devices.yaml"
TOOLS = HERE / "device_tools.json"
LABELS = {"mac": "MacBook", "iphone": "My iPhone", "pixel": "Pixel 7"}
KINDS = {"mac": "mac", "iphone": "ios", "pixel": "android"}
PASSWORD = "evaluation-only-password"  # pragma: allowlist secret

# "You must talk from that device", in the ways it has been said: she reaches them all from here.
FALSE_REFUSAL = re.compile(
    r"(?:talk|speak|ask)(?:ing)?\s+(?:to me\s+|with me\s+)?(?:directly\s+)?"
    r"(?:from|on)\s+(?:the|your)\s+"
    r"(?:mac|macbook|laptop|computer|iphone|phone|pixel)"
    r"|(?:from|on)\s+(?:the|your)\s+(?:mac|macbook|laptop|iphone|phone|pixel)\s+itself"
    r"|se\s+hi\s+(?:baat|pooch|puch)"
    r"|से\s+ही\s+(?:बात|पूछ)"
    r"|(?:par|pe)\s+ja\s*(?:kar|ke)\s+(?:pooch|puch|baat)"
    r"|(?:पर|पे)\s+जा\s*(?:कर|के)\s+(?:पूछ|बात)"
    r"|वहीं\s+से\s+(?:बात|पूछ)",
    re.IGNORECASE,
)
# The server's own words for what went wrong, never meant for the person.
LEAKED = re.compile(r"unknown tool|tool_call|ToolError|Traceback", re.IGNORECASE)
NUMBER = re.compile(r"\d[\d,:.]*\d|\d")
# Counting what was shown ("3 apps") is not inventing a number.
SMALL = 12
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


@dataclass
class Case:
    id: str
    group: str
    origin: str
    say: str
    tools: list[str] = field(default_factory=list)
    device: str | None = None
    then: list[str] = field(default_factory=list)
    proposed: bool = False
    no_tool: bool = False
    never: list[str] = field(default_factory=list)
    offline: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    says: str = ""


@dataclass
class Turn:
    """What happened in a turn: `ran` and `waiting` are (tool, device) pairs."""

    reply: str = ""
    ran: list[tuple[str, str]] = field(default_factory=list)
    waiting: list[tuple[str, str]] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)
    seen: str = ""  # everything the model was given: what it may quote numbers from
    error: str | None = None


@dataclass
class Result:
    id: str
    group: str
    origin: str
    say: str
    ok: bool
    problems: list[str]
    ran: list[str]
    waiting: list[str]
    reply: str
    seconds: float


@dataclass
class Report:
    model: str
    results: list[Result] = field(default_factory=list)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    seconds: float = 0.0


def load_world(path: Path = CASES) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["world"]


def load_cases(path: Path = CASES) -> list[Case]:
    cases = []
    for raw in yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]:
        tool = raw.get("tool") or []
        cases.append(
            Case(
                id=raw["id"],
                group=raw["group"],
                origin=raw["from"],
                say=raw["say"],
                tools=[tool] if isinstance(tool, str) else list(tool),
                device=raw.get("device"),
                then=raw.get("then") or [],
                proposed=bool(raw.get("proposed")),
                no_tool=bool(raw.get("no_tool")),
                never=raw.get("never") or [],
                offline=raw.get("offline") or [],
                errors=raw.get("errors") or {},
                says=raw.get("says") or "",
            )
        )
    return cases


def load_tools(path: Path = TOOLS) -> dict[str, list[dict[str, Any]]]:
    return json.loads(path.read_text(encoding="utf-8"))


def invented_numbers(reply: str, seen: str) -> list[str]:
    """Numbers in the answer that nothing gave the model. A small one may be a count."""
    known = set(NUMBER.findall(seen.translate(DEVANAGARI_DIGITS)))
    digits_seen = {n.replace(",", "") for n in known}
    out = []
    for number in NUMBER.findall(reply.translate(DEVANAGARI_DIGITS)):
        plain = number.replace(",", "").rstrip(":.")
        if plain.isdigit() and int(plain) <= SMALL:
            continue
        if plain in digits_seen or any(plain in n for n in digits_seen):
            continue
        out.append(number)
    return out


def score(case: Case, turn: Turn) -> list[str]:
    """What is wrong with this turn: nothing, for a good one."""
    problems: list[str] = []
    if turn.error:
        problems.append(f"the turn failed: {turn.error}")
    if not turn.reply.strip() and not turn.waiting:
        problems.append("no answer")
    used = [tool for tool, _ in turn.ran + turn.waiting]
    if FALSE_REFUSAL.search(turn.reply):
        problems.append("told them to talk from another device")
    if LEAKED.search(turn.reply):
        problems.append("leaked a tool's internal words")
    made_up = invented_numbers(turn.reply, f"{turn.seen} {case.say}")
    if made_up:
        problems.append(f"a number from nowhere: {', '.join(made_up)}")
    if case.no_tool and used:
        problems.append(f"used a tool for no reason: {', '.join(used)}")
    for tool in case.never:
        if tool in used:
            problems.append(f"must not use {tool}")
    if case.tools:
        pairs = turn.waiting if case.proposed else turn.ran + turn.waiting
        matching = [(tool, device) for tool, device in pairs if tool in case.tools]
        if not matching:
            what = "ask for a yes to" if case.proposed else "use"
            problems.append(f"did not {what} {' or '.join(case.tools)}; used: {used or 'nothing'}")
        elif case.device and all(device != case.device for _, device in matching):
            wrong = ", ".join(f"{tool} on {device}" for tool, device in matching)
            problems.append(f"wrong device: {wrong}, wanted {case.device}")
    if case.proposed:
        ran = [tool for tool, _ in turn.ran if tool in case.tools]
        if ran:
            problems.append(f"ran {ran[0]} on another device without a yes")
        if turn.waiting and case.device:
            label = LABELS[case.device]
            if not any(label in summary for summary in turn.summaries):
                problems.append(f"the yes does not name {label}")
    position = 0
    for tool in case.then:
        try:
            position = used.index(tool, position) + 1
        except ValueError:
            problems.append(f"did not go on to {tool}; used: {used}")
            break
    if case.says and not re.search(case.says, turn.reply):
        problems.append(f"the answer lacks {case.says!r}")
    return problems


class Socket:
    async def send_text(self, data: str) -> None:
        pass

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        pass


class World:
    """One person's three stand-in devices, on a real hub."""

    def __init__(self, runtime: Any, tools: dict[str, list[dict[str, Any]]], results: dict) -> None:
        self.runtime = runtime
        self.tools = tools
        self.results = results
        self.owner = runtime.accounts.create_first_owner("eval@example.com", PASSWORD)
        self.devices: dict[str, Any] = {}
        hub = runtime.hub
        for name, label in LABELS.items():
            skills = sorted({str(t["skill"]) for t in tools[name] if t.get("skill")})
            code, _ = hub.devices.start_pairing(self.owner.id, KINDS[name], label, skills)
            _, device = hub.devices.redeem(code)
            hub.devices.hello(device.id, version="eval", tools=tools[name])
            self.devices[name] = hub.devices.get(device.id)
        self.names = {device.id: name for name, device in self.devices.items()}
        self.ran: list[tuple[str, str]] = []
        self.errors: dict[str, str] = {}
        self.given: list[str] = []
        hub.call = self.call

    def connect(self, offline: list[str]) -> None:
        """All connected, but for those."""
        hub = self.runtime.hub
        hub.connections.clear()
        for index, (name, device) in enumerate(self.devices.items()):
            if name in offline:
                continue
            offered = {
                raw["name"]: DeviceTool(
                    raw["name"],
                    raw.get("description", ""),
                    raw.get("parameters", {"type": "object", "properties": {}}),
                    raw.get("skill"),
                    int(raw.get("tier", 2)),
                )
                for raw in self.tools[name]
            }
            hub.connections[device.id] = Connection(device, Socket(), offered, float(index))

    async def call(self, device_id: int, name: str, arguments: dict[str, Any]) -> Any:
        self.ran.append((name, self.names[device_id]))
        if name in self.errors:
            self.given.append(self.errors[name])
            raise ToolError(self.errors[name])
        result = self.results.get(name, {"summary": "Done."})
        self.given.append(json.dumps(result, ensure_ascii=False))
        return result


async def run_case(runtime: Any, world: World, case: Case) -> Turn:
    turn = Turn()
    world.ran, world.given = [], []
    world.errors = case.errors
    world.connect(case.offline)
    device = world.devices.get(case.origin)
    try:
        async for event in runtime.assistant.events(
            case.say,
            conversation_id=f"eval:{case.id}",
            channel="api",
            actor=world.owner.email,
            user_id=world.owner.id,
            device_id=device.id if device else None,
        ):
            if event["type"] == "action":
                action = event["action"]
                pending = runtime.guard.get(action["id"])
                target = world.names.get(pending.device_id) if pending else None
                turn.waiting.append((str(action.get("tool")), target or "server"))
                turn.summaries.append(str(action.get("summary", "")))
            elif event["type"] == "done":
                turn.reply = str(event.get("text") or "")
            elif event["type"] == "tool_result":
                turn.seen += f" {json.dumps(event, ensure_ascii=False, default=str)}"
    except Exception as exc:  # a failed case is scored, not fatal
        turn.error = f"{type(exc).__name__}: {exc}"[:300]
    turn.ran = list(world.ran)
    turn.seen += " " + " ".join(world.given)
    return turn


async def run_cases(runtime: Any, cases: list[Case]) -> Report:
    world = World(runtime, load_tools(), load_world())
    report = Report(model=", ".join(runtime.gateway.tiers.get(runtime.assistant.tier, [])))
    began = time.monotonic()
    for case in cases:
        started = time.monotonic()
        turn = await run_case(runtime, world, case)
        problems = score(case, turn)
        report.results.append(
            Result(
                id=case.id,
                group=case.group,
                origin=case.origin,
                say=case.say,
                ok=not problems,
                problems=problems,
                ran=[f"{tool}@{device}" for tool, device in turn.ran],
                waiting=[f"{tool}@{device}" for tool, device in turn.waiting],
                reply=turn.reply,
                seconds=round(time.monotonic() - started, 2),
            )
        )
    report.seconds = round(time.monotonic() - began, 1)
    row = runtime.store.one(
        "SELECT COUNT(*) AS calls, SUM(input_tokens) AS input, SUM(output_tokens) AS output, "
        "SUM(cost_usd) AS cost FROM calls"
    )
    if row is not None:
        report.calls = row["calls"] or 0
        report.input_tokens = row["input"] or 0
        report.output_tokens = row["output"] or 0
        report.cost_usd = row["cost"]
    return report


async def run(
    settings: Settings, *, group: str | None, only: str | None, limit: int | None
) -> Report:
    from ira.runtime import build_runtime
    from ira.store import Store
    from ira.tools.registry import ToolRegistry

    runtime = build_runtime(
        settings, registry=ToolRegistry(), store=Store(":memory:"), load_tools=False
    )
    cases = [
        c for c in load_cases() if group in (None, c.group) and (only is None or only in c.id)
    ][:limit]
    try:
        return await run_cases(runtime, cases)
    finally:
        await runtime.aclose()


def render(report: Report) -> str:
    """The scorecard: pass or fail per case, with the model's own words."""
    passed = sum(r.ok for r in report.results)
    cost = "unknown" if report.cost_usd is None else f"${report.cost_usd:.4f}"
    lines = [
        "# Ira's device scorecard",
        "",
        f"**{passed} of {len(report.results)} passed.** Model: {report.model}. "
        f"{report.calls} model calls, {report.input_tokens} tokens in, "
        f"{report.output_tokens} out, cost {cost}, {report.seconds} s.",
        "",
        "| Group | Passed |",
        "|---|---|",
    ]
    for group in dict.fromkeys(r.group for r in report.results):
        some = [r for r in report.results if r.group == group]
        lines.append(f"| {group} | {sum(r.ok for r in some)} of {len(some)} |")
    lines += ["", "| | Case | From | Said | Used | Waiting for a yes | Problems | Ira said |"]
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in report.results:
        cells = [
            "pass" if r.ok else "FAIL",
            r.id,
            r.origin,
            r.say,
            ", ".join(r.ran),
            ", ".join(r.waiting),
            "; ".join(r.problems),
            r.reply[:400],
        ]
        lines.append(
            "| " + " | ".join(c.replace("|", "/").replace("\n", " ") for c in cells) + " |"
        )
    return "\n".join(lines) + "\n"


def main(
    settings: Settings,
    *,
    group: str | None = None,
    only: str | None = None,
    limit: int | None = None,
    out: str | None = None,
    as_json: bool = False,
) -> int:
    report = asyncio.run(run(settings, group=group, only=only, limit=limit))
    card = render(report)
    if out:
        Path(out).write_text(card, encoding="utf-8")
    if as_json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print(card)
    return 0
