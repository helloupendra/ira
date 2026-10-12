"""Request and response models for the HTTP API (they also shape the OpenAPI document)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, RootModel

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
    pin: str = Field(min_length=4, max_length=12)


class ActionOutcome(BaseModel):
    status: str
    message: str
    action: ActionView | None = None
    result: Any = None
    attempts_left: int | None = None
    locked_seconds: int | None = None


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
    since: float = Field(description="Start of today, server local time (epoch seconds).")
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
    tried: str
    attempts: int
    ok: bool
    error_kind: str | None
    seconds: float
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class ConversationRow(BaseModel):
    id: str
    channel: str
    user_id: int | None
    email: str | None
    started_at: float
    last_at: float
    turns: int
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

    id: str
    tool: str
    summary: str
    status: str = Field(
        description="pending, executing, executed, failed, cancelled or expired. A proposal "
        "past expires_at reads expired, never pending."
    )
    expires_at: float


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
    action: MessageAction | None = Field(
        default=None,
        description="For a tool result that proposed an action: that action now, with its "
        "current status. null for every other message, and for a proposal stored before "
        "this field whose action could not be matched.",
    )


class ActionRow(BaseModel):
    id: str
    tool: str
    params: dict[str, Any]
    summary: str
    conversation_id: str | None
    channel: str | None
    actor: str | None = Field(description="Who proposed it.")
    created_at: float
    expires_at: float
    status: str
    result: Any = None
    finished_at: float | None
    decided_by: str | None = Field(
        default=None, description="Who confirmed or cancelled it, from the audit log."
    )
    decided_at: float | None = None


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
    actor: str | None
    channel: str | None
    detail: str | None


class ToolDetail(BaseModel):
    name: str
    kind: str
    description: str
    parameters: dict[str, Any]
    enabled: bool = True
    confirm_roles: list[str] | None = Field(
        default=None, description="Action tools: the roles that may confirm them."
    )


class ChannelView(BaseModel):
    name: str
    enabled: bool
    detail: dict[str, Any] = Field(default_factory=dict)


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


class PinSetRequest(BaseModel):
    password: str = Field(max_length=1024, description="Your account password, checked again.")
    pin: str = Field(min_length=4, max_length=12, pattern=r"^\d{4,12}$")


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


class AdminSessionRow(SessionView):
    user_id: int
    email: str


class SessionsEnded(BaseModel):
    ended: int = Field(description="How many sessions were signed out.")


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
    ok: bool
    seconds: float
    result: Any = None
    error: str | None = None


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


class ModelsView(BaseModel):
    tiers: list[TierView]
    providers: list[ProviderView]
    cooling: dict[str, float] = Field(description="Models on a cool-down: seconds left.")


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
    actor: str
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
