"""Drop over HTTP: a person's own inbox, from the web app, their devices or the CLI."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ira.accounts import Principal
from ira.channels.deps import get_runtime, require
from ira.drop import DropError, Item
from ira.runtime import Runtime

router = APIRouter(prefix="/v1/me/drop", tags=["drop"])
# Drop needs its own permission: a session or a paired device has it, an API token only
# when made with it. A key that may only ask (Siri's) cannot read the inbox.


class DropItem(BaseModel):
    id: int
    kind: str = Field(description="text, link or file.")
    text: str | None = Field(default=None, description="The text or link; a file's caption.")
    name: str | None = None
    mime: str | None = None
    size: int | None = Field(default=None, description="A file's size in bytes.")
    sha256: str | None = Field(default=None, description="A file's SHA-256, hex.")
    from_device_id: int | None = None
    from_label: str = Field(description="The device's name, or Web, Telegram, CLI.")
    created_at: str
    expires_at: str


class DropList(BaseModel):
    items: list[DropItem] = Field(description="Newest first.")
    has_more: bool


class DropText(BaseModel):
    text: str = Field(max_length=1_000_000)


def source(runtime: Runtime, who: Principal) -> tuple[str, int | None]:
    """Where an item came from: a device's own name, or Web, CLI, Telegram."""
    if who.via == "device" and (who.credential_id or "").startswith("device:"):
        device_id = int((who.credential_id or "device:0").split(":", 1)[1])
        device = runtime.hub.devices.get(device_id) if runtime.hub is not None else None
        return (device.label if device else "A device"), device_id
    return {"session": "Web", "token": "CLI", "telegram": "Telegram"}.get(who.via, "Web"), None


async def announce(
    runtime: Runtime, user_id: int, frame: dict[str, Any], except_device: int | None
) -> None:
    """Tell the person's other devices at once; the offline ones catch up with after_id."""
    await runtime.drop_changed(user_id, frame, except_device=except_device)


def _refused(exc: DropError) -> HTTPException:
    return HTTPException(exc.status, detail=str(exc))


@router.post(
    "",
    status_code=201,
    response_model=DropItem,
    summary="Drop text or a link (JSON {text}), or a file (multipart: file, and text as a caption)",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {"schema": DropText.model_json_schema()},
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "text": {"type": "string"},
                        },
                        "required": ["file"],
                    }
                },
            }
        }
    },
)
async def drop(
    request: Request,
    who: Principal = Depends(require("drop")),
    runtime: Runtime = Depends(get_runtime),
) -> DropItem:
    label, device_id = source(runtime, who)
    kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
    try:
        if kind == "multipart/form-data":
            form = await request.form(max_files=1, max_fields=4)
            upload = form.get("file")
            if upload is None or not hasattr(upload, "file"):
                raise DropError("send the file as the multipart field 'file'")
            caption = form.get("text")
            item = await asyncio.to_thread(
                runtime.drop.add_file,
                who.user.id,
                upload.file,  # type: ignore[union-attr]
                upload.filename,  # type: ignore[union-attr]
                upload.content_type,  # type: ignore[union-attr]
                caption=caption if isinstance(caption, str) else None,
                from_label=label,
                from_device_id=device_id,
            )
        else:
            try:
                body = DropText.model_validate(await request.json())
            except ValueError:
                raise DropError('send JSON {"text": "..."}, or a file as multipart') from None
            item = runtime.drop.add_text(
                who.user.id, body.text, from_label=label, from_device_id=device_id
            )
    except DropError as exc:
        raise _refused(exc) from None
    view = item.public()
    await announce(runtime, who.user.id, {"type": "drop", "event": "new", "item": view}, device_id)
    return DropItem(**view)


class DropSettings(BaseModel):
    telegram: bool = Field(
        description="New items from your other devices go to your paired Telegram chat."
    )
    telegram_ready: bool = Field(
        description="This server forwards to Telegram, and you have a paired chat."
    )


class DropSettingsChange(BaseModel):
    telegram: bool


def _settings(runtime: Runtime, user_id: int) -> DropSettings:
    paired = runtime.store.one(
        "SELECT 1 AS yes FROM telegram_chats WHERE user_id = ? LIMIT 1", (user_id,)
    )
    return DropSettings(
        telegram=runtime.assistant.user_settings.get(user_id).drop_telegram,
        telegram_ready=bool(paired) and runtime.settings.drop.telegram_forward,
    )


@router.get("/settings", response_model=DropSettings, summary="Your Drop's settings")
def drop_settings(
    who: Principal = Depends(require("drop")), runtime: Runtime = Depends(get_runtime)
) -> DropSettings:
    return _settings(runtime, who.user.id)


@router.patch("/settings", response_model=DropSettings, summary="Change your Drop's settings")
def change_drop_settings(
    body: DropSettingsChange,
    who: Principal = Depends(require("drop")),
    runtime: Runtime = Depends(get_runtime),
) -> DropSettings:
    # Your own chat only, so no PIN: off or on as you like.
    runtime.assistant.user_settings.set(
        who.user.id, "drop_telegram", None if body.telegram else False
    )
    return _settings(runtime, who.user.id)


@router.get("", response_model=DropList, summary="Your Drop, newest first")
def list_drop(
    after_id: int | None = Query(None, ge=0, description="Only items newer than this one."),
    limit: int = Query(50, ge=1, le=200),
    who: Principal = Depends(require("drop")),
    runtime: Runtime = Depends(get_runtime),
) -> DropList:
    items = runtime.drop.list(who.user.id, after_id=after_id, limit=limit + 1)
    return DropList(
        items=[DropItem(**i.public()) for i in items[:limit]], has_more=len(items) > limit
    )


def _own(runtime: Runtime, who: Principal, item_id: int) -> Item:
    item = runtime.drop.get(who.user.id, item_id)
    if item is None:
        raise HTTPException(404, detail="no such item")  # someone else's is "not found" too
    return item


@router.get(
    "/{item_id}/file",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
    summary="A dropped file's bytes",
)
def drop_file(
    item_id: int,
    who: Principal = Depends(require("drop")),
    runtime: Runtime = Depends(get_runtime),
) -> StreamingResponse:
    item = _own(runtime, who, item_id)
    if item.kind != "file":
        raise HTTPException(404, detail="that item is not a file")
    name = item.name or "file"
    ascii_name = name.encode("ascii", "replace").decode().replace('"', "'")
    headers = {
        "Content-Disposition": (
            f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"
        ),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    if item.size is not None:
        headers["Content-Length"] = str(item.size)
    return StreamingResponse(
        runtime.drop.stream(item),
        media_type=item.mime or "application/octet-stream",
        headers=headers,
    )


@router.delete("/{item_id}", status_code=204, summary="Delete an item from every device")
async def delete_drop(
    item_id: int,
    who: Principal = Depends(require("drop")),
    runtime: Runtime = Depends(get_runtime),
) -> Response:
    _own(runtime, who, item_id)
    runtime.drop.delete(who.user.id, item_id)
    _, device_id = source(runtime, who)
    frame = {"type": "drop", "event": "deleted", "id": item_id}
    await announce(runtime, who.user.id, frame, device_id)
    return Response(status_code=204)
