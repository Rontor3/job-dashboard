"""Who is writing, what changed, and the human's confirmations (job_dashboard/changes.py, confirm.py).

``ChangeMiddleware`` wraps every /api request:
- binds the actor: the agent service sends ``X-Agent-Session`` / ``X-Agent-Message``; anything else is the UI;
- refuses agent requests to human-only routes (Confirm, secret values, résumé upload);
- refuses an agent request to a consequential route unless ``X-Confirm-Token`` is a confirmed, unused token
  issued for exactly that request;
- answers with ``X-Changes``: the change-log rows the request wrote, so the agent can show Undo chips;
- logs any other successful write as an action, so the history is complete.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from job_dashboard import changes, confirm
from job_dashboard.db import init_db

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
# Only a human may: press Confirm, enter a secret value, upload a résumé.
HUMAN_ONLY = [(m, re.compile(p + r"$")) for m, p in (
    ("POST", r"/api/confirmations/\d+/confirm"),
    ("PUT", r"/api/secrets/[A-Z0-9_]+"),
    ("PUT", r"/api/current-resume"),
    ("POST", r"/api/apply-sessions/\d+/resume"),
)]


def _human_only(method: str, path: str) -> bool:
    return any(m == method and p.match(path) for m, p in HUMAN_ONLY)


async def _send_json(send, status: int, body: dict) -> None:
    raw = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]})
    await send({"type": "http.response.body", "body": raw})


class ChangeMiddleware:
    def __init__(self, app, db_path):
        self.app, self.db_path = app, str(db_path)

    def _db(self):
        conn = init_db(self.db_path)
        changes.ensure(conn)
        return conn

    def _consume(self, token, method, path, body) -> bool:
        conn = self._db()
        try:
            return confirm.consume(conn, token, method, path, body)
        finally:
            conn.close()

    def _log_action(self, actor, method, path) -> None:
        token = changes.bind(actor)
        conn = self._db()
        try:
            changes.record(conn, "action", path, method, undoable=False)
        finally:
            conn.close()
            changes.unbind(token)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        method, path = scope["method"].upper(), scope["path"]
        qs = scope.get("query_string", b"").decode("latin-1")
        full_path = path + (f"?{qs}" if qs else "")
        session = headers.get("x-agent-session")
        actor = changes.Actor("agent", session, headers.get("x-agent-message")) if session else changes.Actor()

        if actor.kind == "agent":
            if _human_only(method, path):
                return await _send_json(send, 403, {"detail": "only you can do this, in the dashboard"})
            if confirm.is_consequential(method, path):
                chunks, more = [], True
                while more:
                    msg = await receive()
                    chunks.append(msg.get("body", b""))
                    more = msg.get("more_body", False)
                body = b"".join(chunks)
                ok = await run_in_threadpool(self._consume, headers.get("x-confirm-token"), method, full_path, body)
                if not ok:
                    return await _send_json(send, 403, {"detail": "this needs your confirmation first",
                                                        "needs_confirmation": True})
                sent = False

                async def receive():                       # noqa: F811 — replay the body we read
                    nonlocal sent
                    if sent:
                        return {"type": "http.disconnect"}
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}

        status = {"code": 500}

        async def send_with_changes(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                if actor.changes:
                    hdr = json.dumps(actor.changes, ensure_ascii=True, default=str).encode("latin-1")
                    message = {**message, "headers": [*message.get("headers", []), (b"x-changes", hdr)]}
            await send(message)

        token = changes.bind(actor)
        try:
            await self.app(scope, receive, send_with_changes)
        finally:
            changes.unbind(token)
        if method not in READ_METHODS and status["code"] < 400 and not actor.logged:
            await run_in_threadpool(self._log_action, actor, method, full_path)


class ProposeBody(BaseModel):
    method: str = Field(pattern=r"^(POST|PUT|PATCH|DELETE)$")
    path: str = Field(pattern=r"^/api/", max_length=300)
    body: Optional[dict] = None
    summary: str = Field(min_length=1, max_length=300)


def build_change_router(db_path) -> APIRouter:
    router = APIRouter()

    def db():
        conn = init_db(db_path)
        changes.ensure(conn)
        return conn

    @router.get("/api/changes")
    def list_changes(session_id: str = None, limit: int = 100, before_id: int = None):
        conn = db()
        try:
            return {"changes": changes.listing(conn, session_id, limit, before_id)}
        finally:
            conn.close()

    @router.post("/api/changes/{change_id}/undo")
    def undo_change(change_id: int):
        conn = db()
        try:
            try:
                new_id = changes.undo(conn, change_id)
            except KeyError:
                raise HTTPException(status_code=404, detail="no such change")
            except changes.CannotUndo as e:
                raise HTTPException(status_code=409, detail=str(e))
            return {"ok": True, "undo_id": new_id}
        finally:
            conn.close()

    @router.post("/api/confirmations")
    def propose(body: ProposeBody, request: Request):
        conn = db()
        try:
            try:
                return confirm.propose(conn, request.headers.get("x-agent-session"), body.method, body.path,
                                       body.body, body.summary)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
        finally:
            conn.close()

    @router.get("/api/confirmations")
    def list_confirmations(session_id: str = None, status: str = None):
        conn = db()
        try:
            return {"confirmations": confirm.listing(conn, session_id, status)}
        finally:
            conn.close()

    def decide(conf_id: int, ok: bool):
        conn = db()
        try:
            try:
                return confirm.decide(conn, conf_id, ok)
            except KeyError:
                raise HTTPException(status_code=404, detail="no such confirmation")
            except ValueError as e:
                raise HTTPException(status_code=409, detail=str(e))
        finally:
            conn.close()

    @router.post("/api/confirmations/{conf_id}/confirm")
    def confirm_action(conf_id: int):
        return decide(conf_id, True)

    @router.post("/api/confirmations/{conf_id}/cancel")
    def cancel_action(conf_id: int):
        return decide(conf_id, False)

    return router
