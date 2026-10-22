"""Your own tokens for Siri and other shortcuts: they may only ask, made with your PIN.

A Shortcut on an iPhone ("Hey Siri, Ask Ira") sends what you said to /v1/ask
with one of these. It can ask and nothing else: it cannot confirm an action,
pair a device or read the console, so a lost phone gives away the least.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ira import changes
from ira.accounts import Principal
from ira.channels.deps import get_runtime, require_session
from ira.channels.devices import _check_pin
from ira.channels.schemas import MyToken, MyTokenCreate, OkResponse, TokenCreated
from ira.runtime import Runtime

router = APIRouter(prefix="/v1/me/tokens", tags=["account"])

MAX_TOKENS = 10


def _mine(runtime: Runtime, user_id: int) -> list[MyToken]:
    rows = runtime.store.query(
        "SELECT id, label, scopes, created_at, last_used_at FROM api_tokens "
        "WHERE user_id = ? AND revoked_at IS NULL ORDER BY created_at DESC",
        (user_id,),
    )
    return [
        MyToken(
            id=r["id"],
            label=r["label"],
            scopes=r["scopes"].split(","),
            created_at=r["created_at"],
            last_used_at=r["last_used_at"],
        )
        for r in rows
    ]


@router.get("", response_model=list[MyToken], summary="Your API tokens (never their values)")
def list_my_tokens(
    who: Principal = Depends(require_session("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> list[MyToken]:
    return _mine(runtime, who.user.id)


@router.post(
    "",
    response_model=TokenCreated,
    summary="Make a token that may only ask, for a Siri Shortcut (needs your PIN; shown once)",
)
async def make_my_token(
    body: MyTokenCreate,
    who: Principal = Depends(require_session("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> TokenCreated:
    if len(_mine(runtime, who.user.id)) >= MAX_TOKENS:
        raise HTTPException(409, detail=f"{MAX_TOKENS} tokens at most: remove one first")
    label = " ".join(body.label.split()) or "Siri on iPhone"
    await _check_pin(runtime, who, body.pin, f"make a token for {label}")
    token, token_id = runtime.accounts.create_token(who.user, label, ["ask"])
    changes.record(
        runtime.store,
        who.actor,
        "token.created",
        token_id,
        channel=who.channel,
        after={"label": label, "scopes": ["ask"]},
    )
    return TokenCreated(id=token_id, label=label, scopes=["ask"], token=token)


@router.delete("/{token_id}", response_model=OkResponse, summary="Stop one of your tokens")
def revoke_my_token(
    token_id: str,
    who: Principal = Depends(require_session("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    row = runtime.store.one(
        "SELECT id FROM api_tokens WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
        (token_id, who.user.id),
    )
    if row is None or not runtime.accounts.revoke_token_id(token_id):
        raise HTTPException(404, detail="no such token")
    changes.record(runtime.store, who.actor, "token.revoked", token_id, channel=who.channel)
    return OkResponse()
