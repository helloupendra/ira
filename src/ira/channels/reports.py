"""Reporting an answer: anyone who asked can flag one of Ira's answers to them, and owners
and admins read the reports in the console. Google Play asks every app that shows
AI-generated content for this; the web app and the Mac app offer it too."""

from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from ira import changes
from ira.accounts import Principal
from ira.channels.deps import get_runtime, require, require_session
from ira.channels.schemas import OkResponse, ReportIn, ReportMade, ReportRow
from ira.runtime import Runtime

router = APIRouter(tags=["reports"])


@router.post(
    "/v1/me/reports",
    response_model=ReportMade,
    summary="Report one of Ira's answers to you (wrong, harmful, offensive, private, other)",
)
def report_answer(
    body: ReportIn,
    who: Principal = Depends(require("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> ReportMade:
    row = runtime.store.one(
        "SELECT m.id FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        "WHERE m.id = ? AND m.role = 'assistant' AND c.user_id = ?",
        (body.message_id, who.user.id),
    )
    if row is None:  # someone else's answer is "not found" too
        raise HTTPException(404, detail="no such answer")
    report_id = "rep_" + secrets.token_hex(8)
    note = " ".join((body.note or "").split())[:500] or None
    runtime.store.execute(
        "INSERT INTO reports (id, user_id, message_id, reason, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (report_id, who.user.id, body.message_id, body.reason, note, time.time()),
    )
    return ReportMade(id=report_id)


@router.get(
    "/v1/admin/reports",
    response_model=list[ReportRow],
    summary="Reported answers, newest first (owners and admins)",
)
def list_reports(
    status: str | None = Query(None, pattern="^(open|closed)$"),
    limit: int = Query(100, ge=1, le=500),
    _: Principal = Depends(require("admin.read")),
    runtime: Runtime = Depends(get_runtime),
) -> list[ReportRow]:
    where, params = "", []
    if status:
        where, params = "WHERE r.status = ?", [status]
    rows = runtime.store.query(
        "SELECT r.*, u.email, m.content AS answer, m.model, m.conversation_id "
        "FROM reports r LEFT JOIN users u ON u.id = r.user_id "
        f"LEFT JOIN messages m ON m.id = r.message_id {where} "
        "ORDER BY r.created_at DESC LIMIT ?",
        (*params, limit),
    )
    return [
        ReportRow(
            id=r["id"],
            created_at=r["created_at"],
            email=r["email"],
            reason=r["reason"],
            note=r["note"],
            message_id=r["message_id"],
            conversation_id=r["conversation_id"],
            answer=(r["answer"] or "(deleted)")[:2000],
            model=r["model"],
            status=r["status"],
            closed_at=r["closed_at"],
            closed_by=r["closed_by"],
        )
        for r in rows
    ]


@router.post(
    "/v1/admin/reports/{report_id}/close",
    response_model=OkResponse,
    summary="Mark a report as dealt with",
)
def close_report(
    report_id: str,
    who: Principal = Depends(require_session("admin.write")),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    cursor = runtime.store.execute(
        "UPDATE reports SET status = 'closed', closed_at = ?, closed_by = ? "
        "WHERE id = ? AND status = 'open'",
        (time.time(), who.actor, report_id),
    )
    if cursor.rowcount != 1:
        raise HTTPException(404, detail="no such open report")
    changes.record(runtime.store, who.actor, "report.closed", report_id, channel=who.channel)
    return OkResponse()
