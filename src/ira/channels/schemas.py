"""Request and response models for the HTTP API (they also shape the OpenAPI document)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, RootModel

from ira.security import PIN_MAX_LENGTH, PIN_MIN_LENGTH

CONVERSATION_ID = r"^[A-Za-z0-9_-]{1,64}$"


class AskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(
        default=None,
        pattern=CONVERSATION_ID,
        description="Continue a conversation; omit to start a new one.",
    )


class ActionView(BaseModel):
    id: str
    tool: str
    summary: str
    status: str = Field(description="pending, executing, executed, failed, cancelled or expired.")
    expires_in: int = Field(description="Seconds left to confirm.")
    confirm_roles: list[str] = Field(
        description="The roles that may confirm this action: "
        "actions.tools.<name>.confirm_roles in ira.yaml, or else actions.confirm_roles."
    )
    can_confirm: bool = Field(
        description="Whether the caller may confirm it: their credential has the actions "
        "permission and their role is in confirm_roles. A missing PIN is not counted here; "
        "GET /v1/me/pin says that."
    )
    tier: int = Field(
        default=3,
        description='2: runs on a "yes" from the person who asked (POST /v1/actions/{id}/approve, '
        "or yes typed or spoken in the same conversation). 3: needs a PIN "
        "(POST /v1/actions/{id}/confirm).",
    )
    can_approve: bool = Field(
        default=False,
        description="Tier 2 only: whether the caller is the person who asked, and so may say yes.",
    )


CALL_ID = (
    "Unique within the turn: the model's own call id (the transcript's tool_call_id), "
    "with a suffix such as -2 if the model repeated one."
)
CALL_ARGUMENTS = (
    "The arguments the model passed, as a JSON object; {} when they were not valid JSON."
)
CALL_OK = (
    "False when the call failed: arguments that were not valid JSON or did not fit the "
    "tool's schema, an unknown or switched-off tool, or an error from the tool. "
    "Proposing an action is ok."
)
CALL_RESULT = (
    "The result the model was given, as text (usually JSON), cut to its first 500 "
    'characters. Errors read {"error": "..."}.'
)
CALL_TRUNCATED = 'True when result was cut; it then ends with "…".'


class AskToolCall(BaseModel):
    """A tool the model called while answering, and what it got back."""

    id: str = Field(description=CALL_ID)
    name: str
    arguments: dict[str, Any] = Field(description=CALL_ARGUMENTS)
    ok: bool = Field(description=CALL_OK)
    result: str = Field(description=CALL_RESULT)
    truncated: bool = Field(description=CALL_TRUNCATED)


class AskResponse(BaseModel):
    text: str
    conversation_id: str
    action: ActionView | None = Field(
        default=None, description="An action proposed in this turn, waiting for the PIN."
    )
    tools_used: list[str] = Field(
        default_factory=list,
        description="The names of the tools called, in order. Kept for v0.1 clients; "
        "tool_calls has the details.",
    )
    tool_calls: list[AskToolCall] = Field(
        default_factory=list, description="Each tool call in this turn, in order."
    )
    model: str | None = None
    message_id: int | None = Field(
        default=None, description="The stored answer's id, for POST /v1/me/feedback."
    )


# Server-sent events from POST /v1/ask/stream: one JSON object per `data:` line.


class StartEvent(BaseModel):
    """The turn began."""

    type: Literal["start"]
    conversation_id: str


class ToolEvent(BaseModel):
    """The model called a tool; a tool_result event with the same id follows."""

    type: Literal["tool"]
    id: str = Field(description=CALL_ID)
    name: str
    arguments: dict[str, Any] = Field(description=CALL_ARGUMENTS)


class ToolResultEvent(BaseModel):
    """A tool call finished."""

    type: Literal["tool_result"]
    id: str = Field(description="The id of the tool event this answers.")
    name: str
    ok: bool = Field(description=CALL_OK)
    result: str = Field(description=CALL_RESULT)
    truncated: bool = Field(description=CALL_TRUNCATED)


class ActionEvent(BaseModel):
    """An action was proposed. It waits for a PIN; nothing has run."""

    type: Literal["action"]
    action: ActionView


class DeltaEvent(BaseModel):
    """More answer text."""

    type: Literal["delta"]
    text: str


class ErrorEvent(BaseModel):
    """No model could answer. A done event follows."""

    type: Literal["error"]
    message: str


class DoneEvent(BaseModel):
    """The turn is over. Always the last event."""

    type: Literal["done"]
    text: str = Field(description="The full answer.")
    model: str | None = Field(description="provider:model that answered; null if none did.")
    conversation_id: str
    message_id: int | None = Field(
        default=None, description="The stored answer's id, for POST /v1/me/feedback."
    )


class StreamEvent(
    RootModel[
        Annotated[
            StartEvent
            | ToolEvent
            | ToolResultEvent
            | ActionEvent
            | DeltaEvent
            | ErrorEvent
            | DoneEvent,
            Field(discriminator="type"),
        ]
    ]
):
    """One server-sent event from POST /v1/ask/stream, told apart by `type`."""


class TranscribeResponse(BaseModel):
    text: str
    seconds: float


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    shorten: bool = Field(default=True, description="Strip markdown and cut long answers.")


class ConfirmRequest(BaseModel):
    pin: str = Field(min_length=PIN_MIN_LENGTH, max_length=PIN_MAX_LENGTH)


LOCKED_UNTIL = (
    "When the wrong-PIN lock ends (epoch seconds); null when actions are not locked. "
    "locked_seconds is the same moment as seconds from now."
)


class ActionOutcome(BaseModel):
    status: str
    message: str
    action: ActionView | None = None
    result: Any = None
    attempts_left: int | None = None
    locked_seconds: int | None = None
    locked_until: float | None = Field(default=None, description=LOCKED_UNTIL)


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)
    use_cookie: bool = Field(
        default=True,
        description="true: an HTTP-only session cookie (browsers). "
        "false: the session token in the response body (other clients).",
    )


class SetupRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)
    setup_code: str = Field(description="Printed in the server log while no user exists.")


class UserView(BaseModel):
    id: int
    email: str
    role: str
    created_at: float
    last_login_at: float | None = None


class SessionResponse(BaseModel):
    user: UserView
    permissions: list[str]
    expires_at: float | None = None
    session_token: str | None = Field(
        default=None, description="Only when use_cookie is false. Send as a Bearer token."
    )


class StatusResponse(BaseModel):
    name: str
    version: str
    setup_required: bool


class ToolView(BaseModel):
    name: str
    kind: str
    description: str


class InfoResponse(BaseModel):
    name: str
    version: str
    stt: str | None
    tts: str | None
    browser_stt: Literal["off", "fallback", "prefer"] = Field(
        default="off",
        description="May the web app recognise speech in the browser: when this server has "
        "no speech-to-text (fallback), always (prefer), or never (off).",
    )
    live: bool = Field(
        default=False,
        description="A live call works here (/v1/voice/live): streaming speech-to-text and a "
        "voice, and your role may talk to Ira.",
    )
    mic_language: str = Field(
        default="en-IN",
        description="The language to recognise in the browser, from your languages: hi-IN "
        "when you speak Hindi or Hinglish, else en-IN.",
    )
    tools: list[ToolView]
    user: UserView
    permissions: list[str]


class OkResponse(BaseModel):
    ok: bool = True


class ErrorDetail(BaseModel):
    """Every error: 400 bad input, 401 no or bad credential, 403 not allowed,
    404 not found, 409 conflict, 410 gone, 422 invalid body, 429 too many tries."""

    detail: str | list[dict[str, Any]] = Field(
        description="A sentence for people; a list of field errors on 422."
    )


ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorDetail, "description": text}
    for code, text in {
        400: "Bad input",
        401: "No credential, or an invalid one",
        403: "Not allowed: role, token, or a missing CSRF header",
    }.items()
}


# Admin views.


class ModelUsage(BaseModel):
    model: str | None
    calls: int
    failures: int
    cost_usd: float
    avg_seconds: float


class Overview(BaseModel):
    """Today at a glance. "Today" starts at the server's local midnight: see since."""

    since: float = Field(
        description="The server's local midnight today (epoch seconds). Every count here is "
        "since this moment, in the server's time zone (timezone), not the viewer's."
    )
    since_iso: str = Field(
        description="since as ISO 8601 with the server's UTC offset, e.g. "
        "2026-10-12T00:00:00+05:30."
    )
    timezone: str = Field(
        description="The server's time zone: an IANA name such as Asia/Kolkata when the system "
        "names one, else its UTC offset such as +05:30."
    )
    questions: int = Field(
        description="Questions people asked today, on every channel: the user turns stored "
        "since the start of today. A bare PIN typed into chat is never stored or counted."
    )
    calls: int = Field(
        description="Model calls today. One question can make several (one per tool round), "
        "and model tests count too."
    )
    failures: int = Field(
        description="Model calls today that failed: no model in the chain answered, "
        "or a stream broke off."
    )
    cost_usd: float
    input_tokens: int
    output_tokens: int
    latency_p50: float | None
    latency_p95: float | None
    by_model: list[ModelUsage]
    actions: dict[str, int] = Field(
        description="Actions proposed today, by status. A proposal past its expiry counts "
        "as expired, never pending."
    )
    conversations: int
    users: int


class CallRow(BaseModel):
    id: int
    at: float
    tier: str
    purpose: str
    model: str | None
    tried: str = Field(
        description="The models tried, in order, as provider:model references joined by "
        'commas with no spaces ("openai:gpt-4o-mini,demo:router"). tried_list has them split.'
    )
    tried_list: list[str] = Field(
        default_factory=list, description="The models tried, in order: tried, split at commas."
    )
    attempts: int
    ok: bool
    error_kind: str | None
    seconds: float
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class ConversationRow(BaseModel):
    id: str = Field(description="The stored id, e.g. http:3:kitchen or telegram:5550100.")
    channel: str = Field(description="Where it started: web, api or telegram.")
    user_id: int | None = Field(description="Whose it is; null for rows from before accounts.")
    email: str | None = Field(description="That user's email.")
    started_at: float
    last_at: float = Field(description="Its latest message.")
    turns: int = Field(description="Questions asked in it.")
    preview: str | None = Field(
        default=None, description="The first thing the user said, cut to 120 characters."
    )


class MyConversationRow(BaseModel):
    """One of the caller's own conversations from the web chat or the API."""

    id: str = Field(description="The conversation_id: send it to /v1/ask to continue.")
    channel: str = Field(description="Where it started: web (signed in) or api (a token).")
    started_at: float
    last_at: float
    turns: int = Field(description="Questions asked in it.")
    preview: str | None = Field(
        default=None, description="The first thing you said, cut to 120 characters."
    )


class ToolCallView(BaseModel):
    id: str
    name: str
    arguments: str = Field(description="JSON text exactly as the model produced it.")


class MessageAction(BaseModel):
    """The action a tool call proposed, as it stands now (not as it was then)."""

    id: str = Field(description="The action's id, for /v1/actions/{id}/confirm or cancel.")
    tool: str = Field(description="The action tool it would run.")
    summary: str = Field(description="What it would do, in words written by the tool's code.")
    status: str = Field(
        description="pending, executing, executed, failed, cancelled or expired. A proposal "
        "past expires_at reads expired, never pending."
    )
    expires_at: float = Field(description="When it stops waiting for a PIN (epoch seconds).")
    tier: int = Field(default=3, description='2: waits for a "yes"; 3: waits for a PIN.')


class MessageRow(BaseModel):
    id: int
    at: float
    role: str = Field(description="user, assistant or tool")
    content: str | None = Field(
        description="For role tool: the tool's result as JSON text, exactly as the model saw "
        "it. A proposal's result always reads pending_confirmation; action has its status now."
    )
    tool_calls: list[ToolCallView] = Field(description="Tools an assistant message called.")
    tool_call_id: str | None = Field(description="For role tool: the call this answers.")
    name: str | None = Field(description="For role tool: the tool's name.")
    model: str | None = Field(
        default=None,
        description="For role assistant: the provider:model that wrote it (each tool round "
        "can fall back to another). null when no model wrote it (an error or the step limit), "
        "for other roles, and for messages stored before this field.",
    )
    action: MessageAction | None = Field(
        default=None,
        description="For a tool result that proposed an action: that action now, with its "
        "current status. null for every other message, and for a proposal stored before "
        "this field whose action could not be matched.",
    )
    private: bool = Field(
        default=False,
        description="For role tool: a device's output. Only the conversation's own user sees "
        "its content; anyone else's transcript shows a placeholder instead.",
    )


ACTOR = (
    "Who: the person's email (older rows may hold another name, such as owner or "
    "telegram:<name>). Never the channel; that is in channel."
)


class ActionRow(BaseModel):
    id: str
    tool: str
    params: dict[str, Any]
    summary: str
    conversation_id: str | None
    channel: str | None = Field(description="Where it was proposed: web, api or telegram.")
    actor: str | None = Field(description="Who proposed it. " + ACTOR)
    created_at: float
    expires_at: float
    status: str
    result: Any = None
    finished_at: float | None
    decided_by: str | None = Field(
        default=None,
        description="Who confirmed or cancelled it, from the audit log: an email, as actor.",
    )
    decided_channel: str | None = Field(
        default=None, description="Where it was confirmed or cancelled: web, api or telegram."
    )
    decided_at: float | None = None
    tier: int | None = Field(
        default=None,
        description='2: needed a "yes" from the person who asked; 3: a PIN. null for '
        "actions stored before tiers (they needed a PIN).",
    )
    device_id: int | None = Field(
        default=None,
        description="An action on someone's own device. Unless it is yours, its params, "
        "summary and result are hidden.",
    )


class ActionCounts(BaseModel):
    """Proposed actions by status, over all time or since a moment.

    A proposal past its expiry counts as expired, never pending, here as in
    every list.
    """

    since: float | None = Field(
        description="Only actions proposed at or after this (epoch seconds); null for all time."
    )
    total: int = Field(description="Every action counted, whatever its status.")
    pending: int = Field(default=0, description="Waiting for a PIN, and not yet expired.")
    executing: int = Field(default=0, description="Confirmed and running right now.")
    executed: int = Field(default=0, description="Confirmed and ran.")
    failed: int = Field(default=0, description="Confirmed, ran and failed.")
    cancelled: int = Field(default=0, description="Dropped by someone before it ran.")
    expired: int = Field(default=0, description="Nobody confirmed it in time.")


class AuditRow(BaseModel):
    id: int
    at: float
    action_id: str | None
    tool: str | None
    outcome: str
    actor: str | None = Field(description=ACTOR)
    channel: str | None = Field(description="web, api, telegram or cli.")
    detail: str | None


class ToolDetail(BaseModel):
    name: str
    kind: Literal["read", "action"] = Field(
        description="read runs when the model calls it; action only proposes, and runs after a PIN."
    )
    description: str
    parameters: dict[str, Any]
    enabled: bool = True
    confirm_roles: list[str] | None = Field(
        default=None, description="Action tools: the roles that may confirm them."
    )


class ServerAddress(BaseModel):
    """Where the server listens, and where people open it."""

    host: str = Field(
        description="The address `ira serve` bound: its --host, else channels.http.host."
    )
    port: int = Field(
        description="The port `ira serve` bound: its --port, else channels.http.port."
    )
    configured_host: str = Field(description="channels.http.host in ira.yaml.")
    configured_port: int = Field(description="channels.http.port in ira.yaml.")
    public_url: str | None = Field(
        description="channels.http.public_url, or IRA_PUBLIC_URL: where people reach the "
        "server (for example on a phone, through a TLS proxy). null when not set."
    )
    url: str = Field(
        description="The base URL to open: public_url when set, else http://host:port "
        "(127.0.0.1 for a wildcard host such as 0.0.0.0)."
    )


class ChannelView(BaseModel):
    name: str
    enabled: bool
    detail: dict[str, Any] = Field(
        default_factory=dict,
        description="Untyped details kept for older clients. For http, host and port are "
        "what `ira serve` bound; address has them typed.",
    )
    address: ServerAddress | None = Field(
        default=None, description="For the http channel only: where it listens and is opened."
    )


class TelegramChat(BaseModel):
    """A private chat paired with an account: it acts as that user."""

    chat_id: int = Field(description="Telegram's chat id; DELETE .../telegram/chats/{chat_id}.")
    name: str | None = Field(
        description='The chat\'s name as Telegram gives it, e.g. "Riley Demo (@riley)"; null '
        "for a chat paired before IRA kept names, until it next sends a message."
    )
    paired_at: float = Field(description="When it was paired (epoch seconds).")
    user_id: int = Field(description="The account the chat acts as.")
    email: str = Field(description="That account's email.")
    role: str = Field(description="That account's role now.")


class TelegramView(BaseModel):
    """The Telegram channel: its bot, its state and the chats paired with it."""

    enabled: bool = Field(description="channels.telegram.enabled in ira.yaml.")
    token_env: str = Field(description="The variable that holds the bot token.")
    token_present: bool = Field(description="Whether that variable is set. Never its value.")
    bot_username: str | None = Field(
        description="The bot's username from Telegram's getMe, asked at most once an hour; "
        "null while no token is set or Telegram has not answered."
    )
    bot_link: str | None = Field(description="https://t.me/<bot_username>, to open the bot.")
    bot_error: str | None = Field(
        default=None,
        description="Why getMe failed, if it did (tried again after a minute). Never the token.",
    )
    running: bool = Field(description="Whether the bot is polling Telegram right now.")
    last_poll_at: float | None = Field(
        default=None, description="When the bot last heard from Telegram (epoch seconds)."
    )
    last_error: str | None = Field(default=None, description="The last polling error, if any.")
    pairing_seconds: int = Field(description="How long a pairing code works.")
    chats: list[TelegramChat] = Field(
        description="Every paired chat, newest pairing first; removed users' chats are gone."
    )


class TelegramPairingRequest(BaseModel):
    user_id: int | None = Field(
        default=None,
        description="Whose account the chat will act as; default you. Someone else's needs "
        "the users permission (owner).",
    )


class TelegramPairing(BaseModel):
    """A one-time pairing code. Shown once; only its hash is stored."""

    code: str = Field(description="Eight characters; works once, until expires_at.")
    command: str = Field(description="What to send the bot from the chat: /pair CODE.")
    expires_at: float = Field(description="When the code stops working (epoch seconds).")
    user_id: int = Field(description="The account the chat will act as.")
    email: str = Field(description="That account's email.")
    bot_link: str | None = Field(description="https://t.me/<bot>, when the bot's name is known.")


class TokenRow(BaseModel):
    id: str
    label: str
    email: str
    scopes: str
    created_at: float
    last_used_at: float | None
    revoked_at: float | None


# First-run setup and invitations (public: they carry their own one-time secret).


class SetupStatus(BaseModel):
    needs_owner: bool
    name: str
    version: str


class SetupOwnerRequest(BaseModel):
    code: str = Field(max_length=64, description="Printed by `ira serve` while no user exists.")
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class InviteTokenRequest(BaseModel):
    token: str = Field(max_length=200)


class InviteAcceptRequest(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=1024)


class InviteView(BaseModel):
    id: str
    email: str
    role: str
    created_by: str
    created_at: float
    expires_at: float
    state: str = Field(description="pending, used, revoked or expired")


class PublicInvite(BaseModel):
    email: str
    role: str
    expires_at: float


# The signed-in user's own action PIN.


class PinStatus(BaseModel):
    has_pin: bool
    can_confirm: bool = Field(description="The role has the actions permission.")
    locked_seconds: int | None = Field(
        default=None, description="Actions are locked after wrong PINs, for this long."
    )
    locked_until: float | None = Field(default=None, description=LOCKED_UNTIL)
    pin_set_at: float | None = Field(
        default=None,
        description="When you last set your PIN (epoch seconds). null without a PIN, and for "
        "a PIN set before IRA recorded this.",
    )
    pin_min_length: int = Field(
        default=PIN_MIN_LENGTH, description="The fewest digits a PIN may have."
    )
    pin_max_length: int = Field(
        default=PIN_MAX_LENGTH, description="The most digits a PIN may have."
    )


class PinSetRequest(BaseModel):
    password: str = Field(max_length=1024, description="Your account password, checked again.")
    pin: str = Field(
        min_length=PIN_MIN_LENGTH,
        max_length=PIN_MAX_LENGTH,
        pattern=rf"^\d{{{PIN_MIN_LENGTH},{PIN_MAX_LENGTH}}}$",
    )


# Signed-in sessions. Never the session token or its hash.


class SessionView(BaseModel):
    """A signed-in session that has not expired or been ended."""

    id: str = Field(description="The session's id (ses_...). Not a credential.")
    created_at: float = Field(description="When it signed in.")
    last_used_at: float | None = Field(description="Its latest request.")
    expires_at: float
    current: bool = Field(description="True for the session making this request.")
    user_agent: str | None = Field(
        default=None,
        description="The browser's User-Agent at sign-in, cut to 200 characters; "
        "null when none was sent or the session is older than this field.",
    )
    device: str | None = Field(
        default=None,
        description='A short label read from user_agent on the server, such as "Chrome on '
        'macOS", "Safari on iPhone" or "curl"; null when there is no user_agent to read.',
    )


class AdminSessionRow(SessionView):
    user_id: int
    email: str
    role: str = Field(description="That user's role now: owner, admin, staff or viewer.")


class SessionsEnded(BaseModel):
    ended: int = Field(description="How many sessions were signed out.")


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024, description="10 characters or more.")


class PasswordReset(BaseModel):
    new_password: str = Field(
        max_length=1024, description="10 characters or more. Tell them; they can change it."
    )


class EmailChange(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024, description="Your account password, checked again.")


class EmailSet(BaseModel):
    email: str = Field(max_length=254)


# Console writes.


class AdminUserRow(UserView):
    has_pin: bool


class InviteCreateRequest(BaseModel):
    email: str = Field(max_length=254)
    role: str


class InviteCreated(BaseModel):
    invite: InviteView
    token: str = Field(description="Shown once. Only its hash is stored.")
    path: str = Field(description="Open this path on the server to accept the invitation.")
    url: str | None = Field(
        default=None,
        description="The whole link to send: public_url followed by path, when public_url "
        "is set; null otherwise (join the server's origin and path yourself).",
    )


class RoleChange(BaseModel):
    role: str


class TokenCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    scopes: list[str] = Field(min_length=1)


class TokenCreated(BaseModel):
    id: str
    label: str
    scopes: list[str]
    token: str = Field(description="Shown once. Only its hash is stored.")


class ToolSwitch(BaseModel):
    enabled: bool


class ToolTestRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class ToolTestResult(BaseModel):
    """A test run of a read tool. The HTTP status is 200 whether or not the tool worked."""

    ok: bool = Field(
        description="false when the parameters did not fit the tool's schema, the tool "
        "raised an error, or it gave no result within 30 seconds. Still HTTP 200."
    )
    seconds: float = Field(description="How long the run took.")
    result: Any = Field(
        default=None, description="What the tool returned, when ok; cut at 20,000 characters."
    )
    error: str | None = Field(
        default=None,
        description='Why it failed, when not ok. Bad parameters read "invalid parameters: ...".',
    )


class TierView(BaseModel):
    name: str
    configured: list[str] = Field(description="The chain as ira.yaml lists it.")
    chain: list[str] = Field(description="The chain in use, after any saved reordering.")
    overridden: bool
    used_by_assistant: bool


class ProviderView(BaseModel):
    name: str
    type: str
    in_use: bool = Field(description="Named by a tier or by voice, so it is built at start-up.")
    auth: str
    key_env: str | None = None
    key_present: bool | None = Field(
        default=None, description="Whether the key's variable is set. Never the value."
    )
    last_ok_at: float | None = None
    last_error_at: float | None = None
    last_error_kind: str | None = None


class CoolingReason(BaseModel):
    """Why a model is on a cool-down. Never the provider's own text, a key or a prompt."""

    error_kind: str = Field(
        description="The last error's class: capacity, timeout, auth, bad_request, server, "
        "network or error."
    )
    status: int | None = Field(description="The HTTP status, when the provider answered one.")
    message: str = Field(
        description="A short sentence of the server's own, such as: The provider is busy or "
        "rate-limited (HTTP 429)."
    )


class VoiceOption(BaseModel):
    """A voice id the configured text-to-speech provider accepts."""

    id: str = Field(description="The value for voice.tts.voice, or for PATCH /v1/admin/settings.")
    languages: list[str] = Field(
        description="BCP-47 codes it speaks, e.g. en-IN; empty when it speaks the language of "
        "whatever text it is given."
    )
    gender: str | None = Field(description="female or male, where the provider says.")


class ModelsView(BaseModel):
    tiers: list[TierView]
    providers: list[ProviderView]
    cooling: dict[str, float] = Field(description="Models on a cool-down: seconds left.")
    cooling_reasons: dict[str, CoolingReason] = Field(
        default_factory=dict,
        description="For each model in cooling (the same keys): why it is cooling down.",
    )
    voices: list[VoiceOption] = Field(
        default_factory=list,
        description="Valid voice ids for the text-to-speech provider in use: for polly, its "
        "neural voices for en-IN, hi-IN, en-US and en-GB; for openai, the voices every model "
        "accepts; empty when text-to-speech is off. A static list; ira.yaml may name others.",
    )


class ModelTestRequest(BaseModel):
    ref: str = Field(max_length=200, description="provider:model")


class ModelTestResult(BaseModel):
    ref: str
    ok: bool
    seconds: float
    text: str | None = None
    error_kind: str | None = None
    error: str | None = None


class TierOrderRequest(BaseModel):
    order: list[str] | None = Field(description="The same models in a new order; null resets.")


class KeyView(BaseModel):
    env: str
    used_by: list[str]
    present: bool


class SettingValue(BaseModel):
    value: str | None
    default: str | None
    overridden: bool
    editable: bool = True


class SettingsView(BaseModel):
    name: SettingValue
    voice: SettingValue
    business: str
    tier: str
    stt: str | None
    tts: str | None


class SettingsUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64, description="null resets to ira.yaml")
    voice: str | None = Field(default=None, max_length=64, description="null resets to ira.yaml")


class ChangeRow(BaseModel):
    id: int
    at: float
    actor: str = Field(description=ACTOR)
    channel: str | None = Field(
        default=None,
        description="Where the change was made: web (a signed-in session). Older rows that "
        "named no channel give it from their actor.",
    )
    what: str
    target: str | None
    before: Any = None
    after: Any = None


class CostDay(BaseModel):
    day: str
    calls: int
    failures: int
    cost_usd: float
    input_tokens: int
    output_tokens: int


class ActionRule(BaseModel):
    tool: str
    confirm_roles: list[str]


class SecurityView(BaseModel):
    locked_seconds: int | None
    locked_until: float | None = Field(default=None, description=LOCKED_UNTIL)
    wrong_pins: int
    max_wrong_pins: int
    lock_minutes: float
    expiry_seconds: float
    session_days: float
    cookie_samesite: str
    token_scopes: list[str]
    users_without_pin: list[str]
    confirm_roles: list[str]
    action_rules: list[ActionRule]


class RoleView(BaseModel):
    role: str
    permissions: list[str]
    description: str


# The signed-in person's own assistant: preferences and "What Ira did".


class MySettings(BaseModel):
    """Your own assistant. Each value is yours, or the installation's default."""

    assistant_name: SettingValue = Field(
        description="What you call the assistant; the default is the installation's name."
    )
    wake_phrase: SettingValue = Field(
        description='What your phone listens for (default "Hey Ira"). A phrase of your own needs '
        "a wake-word model trained for it."
    )
    languages: list[str] = Field(
        description="The languages you speak to Ira in: en (English), hi (Hindi, in "
        "Devanagari or Latin letters) and hinglish."
    )
    reply_language: str = Field(
        description="auto: reply in the language you spoke; or always en, hi or hinglish."
    )
    language_options: list[str]
    reply_language_options: list[str]
    web_search: WebSearchState
    timezone: str | None = Field(
        default=None,
        description="Your time zone (IANA, such as Asia/Kolkata), for your routines and "
        "reminders; null: the server's.",
    )


class WebSearchState(BaseModel):
    """Web and news search for you: off until you switch it on, with your PIN."""

    on: bool
    web_ready: bool = Field(
        description="The server has a web search key, so web_search can answer."
    )
    news_ready: bool = Field(description="The server reads news feeds, so news_search can answer.")


class MySettingsUpdate(BaseModel):
    """Send only what changes; null goes back to the default."""

    assistant_name: str | None = Field(default=None, max_length=64)
    wake_phrase: str | None = Field(default=None, max_length=64)
    languages: list[str] | None = Field(default=None, max_length=10)
    reply_language: str | None = Field(default=None, max_length=16)
    web_search: bool | None = Field(
        default=None, description="Switch web and news search on (needs pin) or off."
    )
    timezone: str | None = Field(default=None, max_length=64, description="An IANA name.")
    pin: str | None = Field(
        default=None,
        min_length=PIN_MIN_LENGTH,
        max_length=PIN_MAX_LENGTH,
        description="Your action PIN; needed only to switch web search on.",
    )


class GrantView(BaseModel):
    """Something a person allowed Ira to use: a skill on one of their devices, or web search."""

    id: str = Field(description="device-<device id>-<skill>, or web-<user id>.")
    user_id: int
    email: str | None = None
    kind: Literal["device_skill", "web_search"]
    skill: str
    description: str
    device_id: int | None = None
    device: str | None = Field(default=None, description="The device's name.")


class ActivityRow(BaseModel):
    """One thing Ira did for you: a tool it used or an action that ran. Never its content."""

    id: int
    at: float
    channel: str | None = Field(description="Where you asked: web, api, telegram.")
    tool: str
    device_id: int | None = None
    device: str | None = Field(default=None, description="The device's name, for a device tool.")
    tier: int = Field(description="0 read, 1 small and undoable, 2 needed a yes, 3 needed a PIN.")
    outcome: str = Field(
        description="ok or error (it ran); proposed (it waited for a yes or a PIN); refused "
        "(content from a device or the web asked for it); executed or failed (it ran after "
        "the confirmation)."
    )
    seconds: float | None = None


# Devices: a person's own Mac or Android phone, paired with a one-time code.

DeviceKind = Literal["mac", "android"]


class SkillState(BaseModel):
    name: str = Field(description='A grant, such as "chrome": the tools that belong to it.')
    description: str
    on: bool = Field(description="Switched on by the device's user: its tools are offered.")
    offered: bool = Field(description="The device offers tools for this skill now.")


class DeviceToolView(BaseModel):
    name: str
    description: str
    skill: str
    tier: int = Field(description="0 read, 1 small and undoable, 2 needs a yes, 3 needs a PIN.")
    on: bool = Field(description="Its skill is switched on, so Ira may use it.")


class DeviceView(BaseModel):
    """A paired device. Never its token, and never anything it returned."""

    id: int
    kind: DeviceKind
    label: str
    user_id: int
    email: str | None = Field(default=None, description="Its owner's email.")
    created_at: float
    last_seen_at: float | None = None
    connected: bool = Field(description="Holding its WebSocket now.")
    version: str | None = Field(default=None, description="The client's version, from its hello.")
    tools: list[DeviceToolView] = Field(
        description="The tools its last hello offered (kept while it is offline)."
    )
    skills: list[SkillState]


class PairingCreate(BaseModel):
    kind: DeviceKind
    label: str | None = Field(default=None, max_length=60)
    skills: list[str] = Field(
        default_factory=list, max_length=20, description="Skills to switch on once it pairs."
    )
    pin: str = Field(
        min_length=PIN_MIN_LENGTH,
        max_length=PIN_MAX_LENGTH,
        description="Your action PIN: pairing a device is a new grant.",
    )


class PairingView(BaseModel):
    """A one-time pairing code. Shown once; it works for 10 minutes."""

    id: str
    code: str = Field(description="Eight characters, shown as ABCD-EFGH; type it on the device.")
    expires_at: float
    kind: DeviceKind
    label: str
    skills: list[str]
    server: str = Field(description="The address the device connects to.")
    pair_url: str = Field(description="The link in the QR code: server + /pair#code=...")
    qr_svg: str = Field(description="The QR code of pair_url, as an SVG data: URI.")


class PairingState(BaseModel):
    id: str
    state: Literal["waiting", "paired", "expired"]
    device_id: int | None = None
    expires_at: float


class PairRequest(BaseModel):
    code: str = Field(min_length=8, max_length=20, description="The pairing code.")
    kind: DeviceKind | None = Field(
        default=None, description="The device's kind; must match the code's."
    )


class DevicePaired(BaseModel):
    """The device's own token, shown once. It works on the device WebSocket only."""

    device_id: int
    token: str = Field(
        description="irad_ and 32 random bytes. Keep it in the Keychain or Keystore."
    )
    kind: DeviceKind
    label: str
    skills: list[str]
    name: str = Field(description="What its user calls the assistant.")
    websocket: str = Field(description="The WebSocket's path: /v1/devices/ws.")


class DeviceUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=60)
    skills: list[str] | None = Field(
        default=None, max_length=20, description="The skills to have on: the whole list."
    )
    pin: str | None = Field(
        default=None,
        min_length=PIN_MIN_LENGTH,
        max_length=PIN_MAX_LENGTH,
        description="Your action PIN; needed only to switch a skill on.",
    )


class EventView(BaseModel):
    """Something a device announced, such as a watched tab that finished."""

    id: int
    at: float
    event: str = Field(
        description="From a device: watch_done, task_done or task_failed. From Ira: reminder, "
        "nudge, or learning_question (data.learning_id: answer it with approve or reject)."
    )
    title: str
    text: str
    device_id: int | None = None
    device: str | None = Field(default=None, description="The device's name.")
    data: dict[str, Any] = Field(default_factory=dict)


class DownloadView(BaseModel):
    name: str = Field(description="The file name, as in /v1/downloads/<name>.")
    title: str
    description: str = Field(description="How to install it, in a sentence.")
    available: bool = Field(description="This server has it; else get it from GitHub Releases.")
    url: str = Field(description="Where to download it: here, or the project's releases page.")


class SkillView(BaseModel):
    name: str
    description: str
    kinds: list[str] = Field(description="Which devices offer it.")


class DataDeleteRequest(BaseModel):
    password: str = Field(max_length=1024, description="Your account password, checked again.")


class DataDeleted(BaseModel):
    """What "Delete my data" removed. Your account stays; an owner can remove it."""

    conversations: int
    messages: int
    devices: int
    events: int
    activity: int
    settings: int
    observations: int = 0
    learnings: int = 0
    reminders: int = 0


# Learning: what a person let Ira notice about their day, and what it learned.


class LearningSource(BaseModel):
    name: str = Field(description="phone, conversation or feedback.")
    on: bool
    description: str


class MacRoutine(BaseModel):
    device_id: int
    label: str
    on: bool = Field(description="Its routine skill: lock, sleep, wake and network.")


class NetworkView(BaseModel):
    fingerprint: str = Field(description="A salted hash made on the Mac; never the network's name.")
    label: str | None = Field(description="The name you gave it, such as Office; null until named.")
    device_id: int | None = None
    device: str | None = None
    first_seen: float
    last_seen: float


class PhoneToken(BaseModel):
    id: str
    label: str
    created_at: float
    last_used_at: float | None = None


class ReminderView(BaseModel):
    id: str
    text: str
    trigger: str = Field(description="time, arrive or leave.")
    due_at: float | None = None
    place: str | None = None
    created_at: float
    done_at: float | None = None


class LearningItem(BaseModel):
    id: str
    kind: str = Field(description="time (a routine time), duration, or preference.")
    key: str
    text: str = Field(description="The sentence, written from the evidence: every number is in it.")
    evidence: dict[str, Any]
    confidence: float
    status: str = Field(
        description="proposed (not enough evidence yet), ready, asked, active (you said yes), "
        "rejected, faded (not seen lately) or changed (the numbers moved)."
    )
    created_at: float
    updated_at: float
    asked_at: float | None = None
    decided_at: float | None = None


class LearningView(BaseModel):
    on: bool = Field(description="Learning is on for you. Off: nothing new is noticed.")
    sources: list[LearningSource]
    macs: list[MacRoutine] = Field(description="Your Macs and whether each one's routine is on.")
    days: int = Field(description="How long observations are kept, in days.")
    nudges: bool
    networks: list[NetworkView]
    phone_tokens: list[PhoneToken]
    observations: dict[str, int] = Field(description="How many of each kind are kept.")
    learnings: list[LearningItem]
    reminders: list[ReminderView]


class LearningUpdate(BaseModel):
    on: bool | None = None
    sources: list[str] | None = Field(default=None, max_length=10)
    days: int | None = Field(default=None, ge=14, le=365)
    nudges: bool | None = None
    pin: str | None = Field(
        default=None,
        min_length=PIN_MIN_LENGTH,
        max_length=PIN_MAX_LENGTH,
        description="Your action PIN: needed to switch learning or a source on.",
    )


class NetworkName(BaseModel):
    label: str = Field(
        min_length=1, max_length=40, description="Office, Home: a name, never an address."
    )


class PinOnly(BaseModel):
    pin: str = Field(min_length=PIN_MIN_LENGTH, max_length=PIN_MAX_LENGTH)


class PhoneTokenCreated(BaseModel):
    """Shown once. Its only scope is observe: it can report where you are, nothing else."""

    id: str
    token: str
    url: str = Field(description="Where the Shortcut posts: <server>/v1/observations.")


class ObservationIn(BaseModel):
    """A phone's place event. A place's name only: anything else in the body is refused."""

    model_config = {"extra": "forbid"}

    event: Literal["arrive", "leave"]
    place: str = Field(min_length=1, max_length=40)


class ObservationOut(BaseModel):
    recorded: bool = Field(description="False when learning or the phone source is off.")


class FeedbackIn(BaseModel):
    message_id: int = Field(description="The answer's message_id, from ask or the done event.")
    rating: Literal["up", "down"]
    note: str | None = Field(default=None, max_length=300, description="What would be better.")


class FeedbackKept(BaseModel):
    learned: bool = Field(
        description="True when it was kept: learning and its feedback source are on."
    )


class LearningEdit(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=300,
        description="The sentence, reworded. Its numbers must still be in the evidence.",
    )


class LearningForgotten(BaseModel):
    observations: int = Field(description="How many observations behind it were deleted too.")


class ObservationRow(BaseModel):
    id: int
    at: float
    kind: str
    label: str | None = None
    source: str
    device_id: int | None = None


# Connections: each person's own links to other services (MCP servers).


class ConnectionTool(BaseModel):
    name: str = Field(description="The tool's name for Ira: the connection's slug first.")
    mcp_name: str = Field(description="The tool's own name on its server.")
    description: str | None = None
    tier: int = Field(description="0 reads, 2 needs your yes, 3 your PIN; you may raise it.")
    min_tier: int = Field(description="The lowest tier allowed, from the tool's annotations.")
    enabled: bool


class ConnectionView(BaseModel):
    id: str
    name: str
    slug: str
    kind: Literal["mcp_http", "mcp_stdio", "google", "imap"]
    url: str | None = Field(description="A remote server's address; never its token.")
    server: str | None = Field(description="A local server this IRA offers, by name.")
    enabled: bool
    status: Literal["new", "ok", "error", "needs_auth"]
    error: str | None = None
    created_at: float
    checked_at: float | None = None
    tools: list[ConnectionTool]
    authorize_url: str | None = Field(
        default=None,
        description="Open this to sign in to the service (OAuth); the connection finishes "
        "when the browser comes back.",
    )


class ServerOffer(BaseModel):
    name: str
    description: str
    needs: list[str] = Field(description="What you give it, such as a token, kept sealed.")


class BuiltinOffer(BaseModel):
    kind: Literal["google", "imap"]
    name: str
    description: str
    available: bool = Field(description="False: this server's owner has not set it up.")


class ConnectionsView(BaseModel):
    available: bool = Field(description="False: this server lacks the connectors extra.")
    connections: list[ConnectionView]
    servers: list[ServerOffer]
    builtins: list[BuiltinOffer] = Field(default_factory=list)


class ImapLogin(BaseModel):
    host: str = Field(max_length=253, description="imap.gmail.com, outlook.office365.com, ...")
    user: str = Field(max_length=254)
    password: str = Field(max_length=200, description="An app password, kept sealed.")
    port: int = Field(default=993, ge=1, le=65535)


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40, description="Your name for it: GitHub.")
    url: str | None = Field(default=None, max_length=500, description="A remote MCP server.")
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Sent to a remote server, such as Authorization: Bearer <token>. Sealed.",
    )
    oauth: bool = Field(
        default=False, description="Sign in with the service (OAuth) instead of a token."
    )
    server: str | None = Field(default=None, max_length=40, description="Or a local one, by name.")
    builtin: Literal["google", "imap"] | None = Field(
        default=None, description="Or Google (sign in) or IMAP mail (with imap)."
    )
    imap: ImapLogin | None = None
    env: dict[str, str] = Field(default_factory=dict, description="What a local server needs.")
    pin: str | None = Field(default=None, description="Your action PIN.")


class ConnectionToolChange(BaseModel):
    enabled: bool | None = None
    tier: int | None = Field(default=None, ge=0, le=3)


class ConnectionUpdate(BaseModel):
    enabled: bool | None = None
    tools: dict[str, ConnectionToolChange] = Field(default_factory=dict)
    pin: str | None = Field(default=None, description="Needed to switch a connection back on.")
