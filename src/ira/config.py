"""Configuration: one ``ira.yaml`` for structure, environment variables for secrets.

The YAML never holds a key. A provider names the variable that does
(``api_key_env: OPENAI_API_KEY``), and a ``.env`` file next to the config, or
in the working directory, is loaded into the environment without overriding
variables that are already set.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

CONFIG_ENV = "IRA_CONFIG"
PUBLIC_URL_ENV = "IRA_PUBLIC_URL"


class ConfigError(Exception):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderConfig(_Strict):
    type: Literal["openai", "anthropic", "bedrock_mantle", "fake"]
    base_url: str | None = None
    api_key_env: str | None = None
    auth: Literal["auto", "none", "bearer", "x-api-key", "sigv4"] = "auto"
    region: str | None = None  # bedrock_mantle, or any provider with auth: sigv4
    sigv4_service: str = "bedrock-mantle"
    headers: dict[str, str] = Field(default_factory=dict)
    max_tokens_field: str = "max_tokens"
    stream_usage: bool = True


class PriceConfig(_Strict):
    input: float  # USD per million input tokens
    output: float  # USD per million output tokens
    # Input read from the provider's cache, and written to it. Unset: half the input price
    # and a quarter more than it, the most any of the big providers charge, so a cost is
    # never under-counted. Set the model's own for exact figures.
    cached_input: float | None = Field(default=None, ge=0)
    cache_write: float | None = Field(default=None, ge=0)


def _default_providers() -> dict[str, ProviderConfig]:
    return {"demo": ProviderConfig(type="fake")}


class ModelsConfig(_Strict):
    providers: dict[str, ProviderConfig] = Field(default_factory=_default_providers)
    tiers: dict[str, list[str]] = Field(default_factory=lambda: {"default": ["demo:router"]})
    prices: dict[str, PriceConfig] = Field(default_factory=dict)
    cooldown_seconds: float = 60
    timeout_seconds: float = 60
    max_tokens: int = 1024


class STTConfig(_Strict):
    type: Literal["none", "fake", "transcribe", "chat_audio", "whisper"] = "none"
    provider: str | None = None  # a name under models.providers (chat_audio, whisper)
    model: str | None = None
    # transcribe: Amazon Transcribe streaming. Two or more languages: it tells
    # them apart, preferring the first. "one" (one language per utterance) beat
    # "many" on Hindi, Hinglish and English speech on 22 Oct 2026.
    region: str = "us-east-1"
    languages: list[str] = Field(default_factory=lambda: ["hi-IN", "en-IN"])
    identify: Literal["one", "many"] = "one"
    prompt: str | None = None
    vocabulary: list[str] = Field(default_factory=list)
    fake_text: str = "what are your opening hours"


class TTSConfig(_Strict):
    type: Literal["none", "fake", "polly", "openai"] = "none"
    provider: str | None = None  # for type: openai
    model: str = "tts-1"
    voice: str | None = None
    engine: str = "neural"  # polly
    region: str = "us-east-1"  # polly
    language_code: str | None = None  # polly


class VoiceConfig(_Strict):
    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    # The web app may recognise speech in the browser and send text: "fallback"
    # when this server has no speech-to-text, "prefer" always, "off" never.
    # The browser's recognition may send the audio to its maker (Google, Apple).
    browser_stt: Literal["off", "fallback", "prefer"] = "fallback"
    # The model tier for live calls (a faster one cuts the wait); none: the assistant's.
    tier: str | None = None
    max_spoken_chars: int = 400
    max_audio_seconds: float = 60


class HttpConfig(_Strict):
    host: str = "127.0.0.1"
    port: int = 8765
    # Where people reach this server, e.g. https://ira.example.com behind a TLS
    # proxy. Used for links: the setup banner, invitations, "open on your phone".
    # IRA_PUBLIC_URL overrides it.
    public_url: str | None = None

    @field_validator("public_url")
    @classmethod
    def _check_public_url(cls, value: str | None) -> str | None:
        return check_public_url(value)


def check_public_url(value: str | None) -> str | None:
    """An http(s) origin, optionally with a path; no trailing slash, query or fragment."""
    value = (value or "").strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("public_url must start with http:// or https:// and name a host")
    if parts.query or parts.fragment:
        raise ValueError("public_url cannot have a query or a fragment")
    return value.rstrip("/")


class TelegramConfig(_Strict):
    enabled: bool = False
    token_env: str = "TELEGRAM_BOT_TOKEN"
    # "voice": answer a voice note with voice too; "always"; or "off".
    voice_replies: Literal["off", "voice", "always"] = "voice"


class ChannelsConfig(_Strict):
    http: HttpConfig = Field(default_factory=HttpConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


RoleName = Literal["owner", "admin", "staff", "viewer"]


class ActionRuleConfig(_Strict):
    confirm_roles: list[RoleName]


class ActionsConfig(_Strict):
    expiry_seconds: float = 120
    max_wrong_pins: int = 3
    lock_minutes: float = 15
    # After a PIN on a screen-control action, more on that device runs without asking for
    # this long (0: never); each person may choose off or 5 to 60 (docs/security.md).
    approval_minutes: int = Field(default=15, ge=0, le=60)
    # Who may confirm an action with their own PIN. A role also needs the
    # "actions" permission, which viewers never have.
    confirm_roles: list[RoleName] = Field(default_factory=lambda: ["owner", "admin", "staff"])
    # Per action tool, e.g. {cancel_appointment: {confirm_roles: [owner]}}.
    tools: dict[str, ActionRuleConfig] = Field(default_factory=dict)


LanguageCode = Literal["en", "hi", "hinglish"]


class AssistantConfig(_Strict):
    name: str = "Ira"
    business: str = "your business"
    instructions: str = ""
    tier: str = "default"
    max_tool_rounds: int = 8
    # A tool that has not answered by then is given up on, so one stuck tool never holds a
    # conversation (or a channel) for ever.
    tool_seconds: float = Field(default=45, gt=0, le=600)
    history_messages: int = 30
    # At most this much of a conversation (in characters) goes to the model: old tool
    # results are shortened first, then the oldest whole turns are left out.
    history_chars: int = Field(default=60_000, ge=4_000)
    # The languages people speak to Ira in, and the language it replies in ("auto": the
    # one they spoke). Each person can change both for themselves.
    languages: list[LanguageCode] = Field(default_factory=lambda: ["hinglish", "en", "hi"])
    reply_language: Literal["auto", "en", "hi", "hinglish"] = "auto"
    # How often one person's turns may call one tool, so a model stuck in a loop stops.
    tool_calls_per_minute: int = 30


class FeedConfig(_Strict):
    name: str  # how answers name the source, e.g. "Example News"
    url: str  # an RSS or Atom feed


class NewsConfig(_Strict):
    feeds: list[FeedConfig] = Field(default_factory=list)
    cache_minutes: float = 15
    results: int = 8


class McpServerConfig(_Strict):
    """A local MCP server the operator allows people to connect, each with their own secrets."""

    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    # Variables each person supplies (a token), kept sealed per person.
    person_env: list[str] = Field(default_factory=list)
    description: str = ""


class GoogleConfig(_Strict):
    """The operator's own Google OAuth client, for Gmail and Calendar, read-only."""

    client_id: str | None = None
    client_secret_env: str = "GOOGLE_CLIENT_SECRET"


class DropConfig(_Strict):
    """Drop: each person's private inbox, shared by their own devices."""

    # 95, not 100: a Cloudflare tunnel refuses request bodies over 100 MB on its free plan.
    max_file_mb: int = Field(default=95, ge=1, le=2048)
    max_text: int = Field(default=100_000, ge=100, le=1_000_000)
    quota_mb: int = Field(default=2048, ge=1)  # per person
    keep_days: int = Field(default=30, ge=1, le=3650)
    # Whether a person may have items from their other devices forwarded to their paired
    # Telegram chat. Each person switches it on themselves; it is off until they do.
    telegram_forward: bool = True


class RetentionConfig(_Strict):
    """How long the logs that only grow are kept, in days. ``None`` keeps them, the default
    for all but live calls' timings: the cost log, a person's "What Ira did" and a business's
    audit log stay unless the owner chooses days here. Conversations and Drop have their own
    rules."""

    calls_days: int | None = Field(default=None, ge=1)  # the cost log: model calls, tokens, cost
    voice_days: int | None = Field(default=30, ge=1)  # live calls' timings, never their words
    tool_log_days: int | None = Field(default=None, ge=1)  # "What Ira did"
    audit_days: int | None = Field(default=None, ge=1)  # actions' audit log
    change_log_days: int | None = Field(default=None, ge=1)  # console changes
    # Sessions, invites and pairing codes this long after they ended, expired or were used.
    ended_days: int = Field(default=30, ge=1)


class ConnectorsConfig(_Strict):
    # Local MCP servers people may connect; a person can never add a command themselves.
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    # Remote servers on private, loopback or link-local addresses are refused unless this is
    # true: otherwise a person could make this server reach machines on its own network.
    allow_private: bool = False
    max_tools: int = 40  # per connection, offered to the model
    google: GoogleConfig = Field(default_factory=GoogleConfig)


class SearchConfig(_Strict):
    """Web and news search, which each person switches on for themselves."""

    # A Brave Search API key, in .env. Without it, web_search says it is not configured.
    brave_api_key_env: str = "BRAVE_SEARCH_API_KEY"
    # A YouTube Data API key, in .env, for video_find (Brave finds videos without one).
    youtube_api_key_env: str = "YOUTUBE_API_KEY"
    calls_per_hour: int = 30
    results: int = 5
    country: str | None = None  # two letters, e.g. IN
    search_lang: str | None = None  # e.g. en
    news: NewsConfig = Field(default_factory=NewsConfig)


class Settings(_Strict):
    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    data_dir: Path = Path("data")
    tools: list[str] = Field(default_factory=list)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    actions: ActionsConfig = Field(default_factory=ActionsConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    connectors: ConnectorsConfig = Field(default_factory=ConnectorsConfig)
    drop: DropConfig = Field(default_factory=DropConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    config_dir: Path = Field(default_factory=Path.cwd, exclude=True)

    @field_validator("tools")
    @classmethod
    def _no_empty_tools(cls, value: list[str]) -> list[str]:
        return [v for v in (s.strip() for s in value) if v]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ira.db"


def load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines; never overrides the real environment.

    A folder this user may not look into counts as having no .env: ``sudo -u
    ira ira doctor /srv/ira/x`` starts in the admin's home, which ira cannot
    read. A .env that is there but unreadable is an error worth naming.
    """
    try:
        if not path.is_file():
            return
    except OSError:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror or exc}") from None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def find_config(explicit: str | Path | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return path
    if os.environ.get(CONFIG_ENV):
        return find_config(os.environ[CONFIG_ENV])
    local = Path("ira.yaml")
    return local if local.is_file() else None


def load_settings(path: str | Path | None = None) -> Settings:
    """Read ``ira.yaml`` (or defaults), resolving relative paths against its folder."""
    config_path = find_config(path)
    try:
        cwd: Path | None = Path.cwd()
    except OSError:  # some systems refuse getcwd() in a folder this user cannot read
        cwd = None
    base = config_path.parent if config_path else cwd
    if base is None:
        raise ConfigError("no ira.yaml given, and the working directory cannot be read")
    config_dir = base.resolve()
    load_dotenv(config_dir / ".env")
    if cwd is not None:
        load_dotenv(cwd / ".env")
    raw: dict = {}
    if config_path:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if loaded is not None and not isinstance(loaded, dict):
            raise ConfigError(f"{config_path} must contain a mapping at the top level")
        raw = loaded or {}
    try:
        settings = Settings.model_validate({**raw, "config_dir": config_dir})
    except ValidationError as exc:
        raise ConfigError(f"invalid config {config_path or '(defaults)'}:\n{exc}") from None
    if not settings.data_dir.is_absolute():
        settings.data_dir = config_dir / settings.data_dir
    if os.environ.get(PUBLIC_URL_ENV):
        try:
            public_url = check_public_url(os.environ[PUBLIC_URL_ENV])
        except ValueError as exc:
            raise ConfigError(f"{PUBLIC_URL_ENV}: {exc}") from None
        settings.channels.http.public_url = public_url
    return settings


def secret(name: str | None, *, purpose: str) -> str | None:
    """Read a secret from the environment, or fail naming the variable (never the value)."""
    if not name:
        return None
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"{purpose} needs the environment variable {name}; see .env.example")
    return value
