"""Wire configuration into live objects: store, gateway, tools, voice, accounts."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

from ira import overrides
from ira.accounts import Accounts
from ira.assistant import Assistant
from ira.config import ConfigError, ProviderConfig, Settings, secret
from ira.conversations import Conversations
from ira.devices import DeviceHub, Devices
from ira.models.anthropic import AnthropicProvider
from ira.models.base import ChatProvider
from ira.models.fake import RouterProvider
from ira.models.gateway import Gateway, Price
from ira.models.http import Auth, BearerAuth, HeaderKeyAuth, HttpClient, NoAuth
from ira.models.openai_compat import OpenAICompatProvider
from ira.overrides import DEFAULT_VOICES
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
    setup_code: str | None = None
    setup_code_shown: bool = False
    # What `ira serve` bound, which --host and --port can change from ira.yaml.
    bound_host: str | None = None
    bound_port: int | None = None
    # The Telegram Bot API client, shared by the bot and the console; tests put a fake here.
    telegram_api: Any = None
    # People's paired devices, live.
    hub: DeviceHub | None = None

    def __post_init__(self) -> None:
        if self.hub is None:
            self.hub = DeviceHub(Devices(self.store))
        if self.assistant.personal_tools is None:
            self.assistant.personal_tools = self.personal_tools
        if self.guard.device_runner is None:
            self.guard.device_runner = self.hub.run_action
        self.hub.welcome_extra = self._welcome

    def personal_tools(self, user_id: int | None) -> list[PersonalTool]:
        """One person's own tools for a turn: their devices' tools whose skill is on."""
        assert self.hub is not None
        return self.hub.tools_for(user_id)

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

    def ensure_setup_code(self) -> str | None:
        """While no account exists, a one-time code guards the web setup form.

        The code is printed by ``ira serve`` (and logged), so only someone who
        can see the server's output can claim a freshly exposed install.
        """
        if not self.accounts.needs_owner():
            self.setup_code = None
        elif self.setup_code is None:
            self.setup_code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
        return self.setup_code

    async def aclose(self) -> None:
        for client in self.http_clients:
            await client.aclose()
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
    )
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
