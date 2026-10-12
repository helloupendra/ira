"""Request and response models for the HTTP API (they also shape the OpenAPI document)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

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
    status: str
    expires_in: int = Field(description="Seconds left to confirm.")


class AskResponse(BaseModel):
    text: str
    conversation_id: str
    action: ActionView | None = Field(
        default=None, description="An action proposed in this turn, waiting for the PIN."
    )
    tools_used: list[str] = Field(default_factory=list)
    model: str | None = None


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


# Admin views.


class ModelUsage(BaseModel):
    model: str | None
    calls: int
    failures: int
    cost_usd: float
    avg_seconds: float


class Overview(BaseModel):
    since: float = Field(description="Start of today, server local time (epoch seconds).")
    calls: int
    failures: int
    cost_usd: float
    input_tokens: int
    output_tokens: int
    latency_p50: float | None
    latency_p95: float | None
    by_model: list[ModelUsage]
    actions: dict[str, int]
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


class MessageRow(BaseModel):
    id: int
    at: float
    role: str
    content: str | None
    tool_calls: list[dict[str, Any]]
    tool_call_id: str | None
    name: str | None


class ActionRow(BaseModel):
    id: str
    tool: str
    params: dict[str, Any]
    summary: str
    conversation_id: str | None
    channel: str | None
    actor: str | None
    created_at: float
    expires_at: float
    status: str
    result: Any = None
    finished_at: float | None


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
