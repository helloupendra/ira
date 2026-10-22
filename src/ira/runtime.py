"""Wire configuration into live objects: store, gateway, tools, voice, accounts."""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

from ira import overrides, setupcode
from ira.accounts import Accounts
from ira.approvals import Approvals, covered
from ira.assistant import Assistant
from ira.businesses import Businesses
from ira.config import ConfigError, ProviderConfig, Settings, secret
from ira.conversations import Conversations
from ira.devices import DeviceHub, Devices
from ira.learning.learner import Learner
from ira.learning.people import people_tools
from ira.learning.reminders import reminder_tools
from ira.learning.service import LearningService
from ira.models.anthropic import AnthropicProvider
from ira.models.base import ChatProvider
from ira.models.fake import RouterProvider
from ira.models.gateway import Gateway, Price
from ira.models.http import Auth, BearerAuth, HeaderKeyAuth, HttpClient, NoAuth
from ira.models.openai_compat import OpenAICompatProvider
from ira.overrides import DEFAULT_VOICES
from ira.search import Search
from ira.store import Store
from ira.tools.actions import ActionGuard
from ira.tools.loader import load_tool_modules
from ira.tools.personal import PersonalTool
from ira.tools.registry import ToolContext, ToolRegistry, default_registry
from ira.usersettings import UserSettings
from ira.voice.providers import (
    ChatAudioSTT,
    FakeSTT,
    FakeTTS,
    OpenAITTS,
    PollyTTS,
    SpeechToText,
    TextToSpeech,
    WhisperSTT,
)

log = logging.getLogger("ira")

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}


DEVICE_KINDS = {"mac": "Mac", "android": "Android", "ios": "iPhone"}
MAX_DEVICES_IN_PROMPT = 6


@dataclass
class Runtime:
    settings: Settings
    store: Store
    registry: ToolRegistry
    gateway: Gateway
    guard: ActionGuard
    accounts: Accounts
    conversations: Conversations
    assistant: Assistant
    stt: SpeechToText | None = None
    tts: TextToSpeech | None = None
    http_clients: list[HttpClient] = field(default_factory=list)
    channel_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    setup_code_shown: bool = False
    # What `ira serve` bound, which --host and --port can change from ira.yaml.
    bound_host: str | None = None
    bound_port: int | None = None
    # The Telegram Bot API client, shared by the bot and the console; tests put a fake here.
    telegram_api: Any = None
    # People's paired devices, live.
    hub: DeviceHub | None = None
    # Web and news search, for the people who switched them on.
    search: Search | None = None
    # What each person let Ira notice about their day, and what it learned.
    learning: LearningService | None = None
    learner: Learner | None = None
    # The businesses each person works with, as they described them.
    businesses: Businesses = field(init=False)
    # The live calls open now, by their conversation: a confirmed action carries on in its call.
    live_calls: dict[str, Any] = field(default_factory=dict)
    # Approval windows: one PIN on a screen-control action covers the next steps on a device.
    approvals: Approvals = field(init=False)
    # Each person's connections to other services (MCP servers).
    connectors: Any = None

    def __post_init__(self) -> None:
        if self.hub is None:
            self.hub = DeviceHub(Devices(self.store))
        if self.search is None:
            self.search = Search(self.settings.search)
        if self.learning is None:
            hub = self.hub
            self.learning = LearningService(
                self.store,
                self.assistant.user_settings,
                notify=lambda user_id, event: hub.publish(user_id, None, event),
            )
        self.hub.observer = self.learning.from_device
        if self.learner is None:
            self.learner = Learner(self.learning)
        if self.assistant.memory is None:
            self.assistant.memory = self.learner.memory
        self.businesses = Businesses(self.store)
        if self.assistant.businesses is None:
            self.assistant.businesses = self.businesses.lines
        if self.assistant.switched_off is None:
            self.assistant.switched_off = self.switched_off
        hub = self.hub
        self.approvals = Approvals(
            self.store,
            minutes_for=self.approval_minutes,
            connected=lambda device_id: hub is not None and hub.connected(device_id),
        )
        if self.assistant.approvals is None:
            self.assistant.approvals = self.approvals
            self.assistant.device_label = self.device_label
        if self.guard.after_pin is None:
            self.guard.after_pin = self._after_pin
        if self.assistant.after_turn is None:
            self.assistant.after_turn = self._learn_from
        if self.assistant.personal_tools is None:
            self.assistant.personal_tools = self.personal_tools
        if self.guard.device_runner is None:
            self.guard.device_runner = self.hub.run_action
        if self.guard.personal_runner is None:
            self.guard.personal_runner = self._run_personal_action
        if self.connectors is None:
            from ira.connectors.service import Connectors

            sealer: list[Any] = []

            def seal() -> Any:
                if not sealer:  # made on first use: the key file is not needed until then
                    from ira.connectors.sealed import Sealer, load_key

                    sealer.append(Sealer(load_key(self.settings.data_dir)))
                return sealer[0]

            self.connectors = Connectors(
                self.store,
                seal,
                self.settings.connectors,
                callback_url=self.base_url,
                zone_for=lambda user_id: self.learner.zone(user_id) if self.learner else None,
            )
        self.hub.welcome_extra = self._welcome

    async def _run_personal_action(self, pending: Any) -> Any:
        """A confirmed action of the person's own tool, found again by its name."""
        from ira.tools.registry import ToolError

        for tool in self.personal_tools(pending.user_id):
            if tool.name == pending.tool and tool.device_id is None:
                return await tool.run(pending.params)
        raise ToolError(f"'{pending.tool}' is no longer one of your tools")

    async def _learn_from(self, user_id: int, message: str) -> None:
        """After a turn: what the person said about where they are going, if they allow it."""
        from ira.learning.extract import extract

        assert self.learning is not None
        tier = "fast" if "fast" in self.gateway.tiers else self.assistant.tier
        await extract(self.learning, self.gateway, user_id, message, tier=tier)

    def personal_tools(self, user_id: int | None) -> list[PersonalTool]:
        """One person's own tools for a turn: their devices' tools whose skill is on,
        and web and news search if they switched them on."""
        assert self.hub is not None and self.search is not None
        tools = self.hub.tools_for(user_id)
        if user_id is None:
            return tools
        if self.assistant.user_settings.get(user_id).web_search:
            tools += self.search.tools()
        if self.learning is not None and self.learner is not None:
            tools += reminder_tools(self.learning, user_id, self.learner.zone(user_id))
            tools += people_tools(self.learning.data, user_id)
            tools += self.businesses.tools(user_id)
        if self.connectors is not None:
            tools += self.connectors.tools_for(user_id)
        return tools

    def approval_minutes(self, user_id: int) -> int:
        chosen = self.assistant.user_settings.get(user_id).approval_minutes
        return chosen if chosen is not None else self.settings.actions.approval_minutes

    def device_label(self, device_id: int) -> str:
        device = self.hub.devices.get(device_id) if self.hub is not None else None
        if device is None:
            return "a device"
        return f"{device.label} ({DEVICE_KINDS.get(device.kind, device.kind)})"

    def _after_pin(self, pending: Any) -> None:
        """A PIN confirmed an action: when it was screen control on a device, open (or
        renew) that device's approval window."""
        if pending.device_id is None or pending.user_id is None or self.hub is None:
            return
        device = self.hub.devices.get(pending.device_id)
        skill = None
        if device is not None:
            skill = next(
                (t.get("skill") for t in device.tools if t.get("name") == pending.tool), None
            )
        if covered(pending.tool, skill):
            self.approvals.open(pending.user_id, pending.device_id, pending.id)

    async def going_away(self) -> None:
        """The server was asked to stop: tell devices and live calls first (1001, going away)
        so their apps reconnect to the next server at once, instead of holding it open."""
        if self.hub is not None:
            await self.hub.going_away()
        for call in list(self.live_calls.values()):
            with contextlib.suppress(Exception):
                await call.hang_up()

    async def continue_after(self, outcome: Any, *, actor: str) -> dict[str, Any] | None:
        """After an action ran from its card (a PIN, or a yes), carry its conversation on with
        what it returned: spoken in the live call when one is open on it, otherwise here, and
        the reply is returned ({"text", "message_id"}). None when there is nothing to carry."""
        pending = outcome.action
        if outcome.status not in ("executed", "failed") or pending is None:
            return None
        if not pending.conversation_id:
            return None
        call = self.live_calls.get(pending.conversation_id)
        if call is not None:
            call.follow_up()
            return {"in_call": True}
        text, message_id = "", None
        try:
            async for event in self.assistant.follow_up(
                pending.conversation_id,
                channel=pending.channel or "api",
                actor=actor,
                user_id=pending.user_id,
                stream=False,
            ):
                if event.get("type") == "done":
                    text, message_id = event.get("text") or "", event.get("message_id")
        except Exception:
            log.exception("carrying on after action %s failed", pending.id)
            return None
        return {"text": text, "message_id": message_id}

    def switched_off(self, user_id: int | None) -> list[str]:
        """For each of the person's devices, the skills its tools need that are not switched
        on: "Pixel 7 (Android): calls, contacts". From what the device last reported, so a
        phone that is offline still counts."""
        if user_id is None or self.hub is None:
            return []
        lines = []
        for device in self.hub.devices.for_user(user_id)[:MAX_DEVICES_IN_PROMPT]:
            offered = {
                str(t.get("skill") or str(t.get("name", "")).split("_", 1)[0]) for t in device.tools
            } - {""}
            off = sorted(offered - set(device.skills))
            if off:
                kind = DEVICE_KINDS.get(device.kind, device.kind)
                lines.append(f"{device.label} ({kind}): {', '.join(off[:12])}")
        return lines

    def _welcome(self, user_id: int) -> dict[str, Any]:
        prefs = self.assistant.user_settings.get(user_id)
        return {"assistant": self.assistant.name_for(user_id), "wakePhrase": prefs.wake_phrase}

    @property
    def host(self) -> str:
        return self.bound_host if self.bound_host is not None else self.settings.channels.http.host

    @property
    def port(self) -> int:
        return self.bound_port if self.bound_port is not None else self.settings.channels.http.port

    @property
    def public_url(self) -> str | None:
        return self.settings.channels.http.public_url

    def base_url(self) -> str:
        """Where to open this server: public_url when set, else the address it listens on."""
        return self.public_url or local_url(self.host, self.port)

    @property
    def setup_code(self) -> str | None:
        """The setup code in force, if any; never makes one."""
        return setupcode.current(self.store) if self.accounts.needs_owner() else None

    def ensure_setup_code(self) -> str | None:
        """While no account exists, a one-time code guards the web setup form.

        The code is printed by ``ira serve`` (and logged), so only someone who
        can see the server's output can claim a freshly exposed install. It is
        kept in the database: a restart prints the same link again.
        """
        if not self.accounts.needs_owner():
            setupcode.retire(self.store)
            return None
        code = setupcode.current(self.store)
        if code is None:
            code = setupcode.renew(self.store)
            if self.setup_code_shown:  # the printed one expired while running
                log.warning("The setup code expired. A new link: %s", self.setup_link(code))
        return code

    def setup_link(self, code: str) -> str:
        from ira.web import setup_page

        return f"{self.public_url or ''}{setup_page()}#code={code}"

    async def aclose(self) -> None:
        for client in self.http_clients:
            await client.aclose()
        if self.connectors is not None:
            await self.connectors.close()
        if self.search is not None:
            await self.search.aclose()
        close = getattr(self.telegram_api, "aclose", None)
        if close is not None:
            await close()


def local_url(host: str, port: int) -> str:
    """http://host:port, with 127.0.0.1 for a wildcard address and brackets for IPv6."""
    shown = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    if ":" in shown:
        shown = f"[{shown}]"
    return f"http://{shown}:{port}"


def _auth(name: str, cfg: ProviderConfig) -> Auth:
    mode = cfg.auth
    if mode == "auto":
        if cfg.type == "anthropic":
            mode = "x-api-key"
        elif cfg.type == "bedrock_mantle":
            mode = "bearer" if cfg.api_key_env else "sigv4"
        else:
            mode = "bearer" if cfg.api_key_env else "none"
    if mode == "none":
        return NoAuth()
    if mode == "sigv4":
        from ira.models.aws import SigV4Auth

        return SigV4Auth(cfg.region or "us-east-1", cfg.sigv4_service)
    key = secret(cfg.api_key_env, purpose=f"provider '{name}'")
    if key is None:
        raise ConfigError(f"provider '{name}' uses auth '{mode}' but sets no api_key_env")
    return HeaderKeyAuth(key) if mode == "x-api-key" else BearerAuth(key)


def build_http(name: str, cfg: ProviderConfig) -> HttpClient:
    if cfg.type == "fake":
        raise ConfigError(f"provider '{name}' is a fake and has no HTTP endpoint")
    if cfg.base_url:
        base_url = cfg.base_url
    elif cfg.type == "bedrock_mantle":
        from ira.models.aws import mantle_base_url

        base_url = mantle_base_url(cfg.region or "us-east-1")
    else:
        base_url = DEFAULT_BASE_URLS[cfg.type]
    return HttpClient(base_url, _auth(name, cfg), headers=dict(cfg.headers), label=name)


def build_provider(name: str, cfg: ProviderConfig, http: HttpClient | None) -> ChatProvider:
    if cfg.type == "fake":
        return RouterProvider()
    assert http is not None
    if cfg.type == "anthropic":
        return AnthropicProvider(http)
    return OpenAICompatProvider(
        http, max_tokens_field=cfg.max_tokens_field, stream_usage=cfg.stream_usage
    )


def build_runtime(
    settings: Settings,
    *,
    registry: ToolRegistry | None = None,
    store: Store | None = None,
    load_tools: bool = True,
) -> Runtime:
    store = store or Store(settings.db_path)
    registry = registry if registry is not None else default_registry
    if load_tools and settings.tools:
        ctx = ToolContext(data_dir=settings.data_dir, config_dir=settings.config_dir)
        load_tool_modules(settings.tools, ctx)

    used = {ref.partition(":")[0] for refs in settings.models.tiers.values() for ref in refs}
    voice_providers = {settings.voice.stt.provider, settings.voice.tts.provider} - {None}
    https: dict[str, HttpClient] = {}
    providers: dict[str, ChatProvider] = {}
    for name, cfg in settings.models.providers.items():
        if name not in used and name not in voice_providers:
            continue  # configured but unused: do not demand its key
        http = build_http(name, cfg) if cfg.type != "fake" else None
        if http is not None:
            https[name] = http
        providers[name] = build_provider(name, cfg, http)

    gateway = Gateway(
        providers,
        settings.models.tiers,
        prices={ref: Price(p.input, p.output) for ref, p in settings.models.prices.items()},
        store=store,
        cooldown_seconds=settings.models.cooldown_seconds,
        timeout_seconds=settings.models.timeout_seconds,
        max_tokens=settings.models.max_tokens,
    )
    guard = ActionGuard(
        store,
        registry,
        expiry_seconds=settings.actions.expiry_seconds,
        max_wrong_pins=settings.actions.max_wrong_pins,
        lock_seconds=settings.actions.lock_minutes * 60,
        confirm_roles=settings.actions.confirm_roles,
        tool_confirm_roles={
            name: rule.confirm_roles for name, rule in settings.actions.tools.items()
        },
    )
    for name in settings.actions.tools:
        tool = registry.get(name)
        if tool is None or tool.kind != "action":
            log.warning("actions.tools names '%s', which is not a registered action tool", name)
    conversations = Conversations(store)
    if settings.voice.tier and settings.voice.tier not in settings.models.tiers:
        raise ConfigError(f"voice.tier '{settings.voice.tier}' is not a tier in models.tiers")
    assistant = Assistant(
        gateway,
        registry,
        guard,
        store,
        conversations,
        name=settings.assistant.name,
        business=settings.assistant.business,
        instructions=settings.assistant.instructions,
        tier=settings.assistant.tier,
        max_tool_rounds=settings.assistant.max_tool_rounds,
        history_messages=settings.assistant.history_messages,
        user_settings=UserSettings(
            store,
            languages=list(settings.assistant.languages),
            reply_language=settings.assistant.reply_language,
        ),
        tool_calls_per_minute=settings.assistant.tool_calls_per_minute,
    )
    assistant.voice_tier = settings.voice.tier
    runtime = Runtime(
        settings=settings,
        store=store,
        registry=registry,
        gateway=gateway,
        guard=guard,
        accounts=Accounts(store),
        conversations=conversations,
        assistant=assistant,
        stt=build_stt(settings, https),
        tts=build_tts(settings, https),
        http_clients=list(https.values()),
    )
    overrides.apply(runtime)
    return runtime


def _voice_http(kind: str, provider: str | None, https: dict[str, HttpClient]) -> HttpClient:
    if not provider or provider not in https:
        raise ConfigError(f"voice {kind} needs 'provider' naming an HTTP provider in models")
    return https[provider]


def build_stt(settings: Settings, https: dict[str, HttpClient]) -> SpeechToText | None:
    cfg = settings.voice.stt
    if cfg.type == "none":
        return None
    if cfg.type == "fake":
        return FakeSTT(cfg.fake_text)
    if cfg.type == "transcribe":
        from ira.voice.transcribe import TranscribeSTT

        return TranscribeSTT(cfg.region, cfg.languages, identify=cfg.identify)
    http = _voice_http("stt", cfg.provider, https)
    if cfg.type == "whisper":
        return WhisperSTT(http, cfg.model or "whisper-1", prompt=cfg.prompt)
    if not cfg.model:
        raise ConfigError("voice.stt.model is required for type chat_audio")
    return ChatAudioSTT(http, cfg.model, prompt=cfg.prompt, vocabulary=cfg.vocabulary)


def build_tts(settings: Settings, https: dict[str, HttpClient]) -> TextToSpeech | None:
    cfg = settings.voice.tts
    if cfg.type == "none":
        return None
    if cfg.type == "fake":
        return FakeTTS(cfg.voice or DEFAULT_VOICES["fake"])
    if cfg.type == "polly":
        return PollyTTS(
            voice=cfg.voice or DEFAULT_VOICES["polly"],
            engine=cfg.engine,
            region=cfg.region,
            language_code=cfg.language_code,
        )
    return OpenAITTS(
        _voice_http("tts", cfg.provider, https), cfg.model, cfg.voice or DEFAULT_VOICES["openai"]
    )
