"""The Inbox's updates feed (notifications.py).

    GET  /api/notifications                  {items, unread}: newest first, dismissed ones left out
    POST /api/notifications/read             {ids?}: mark these (or all) read
    POST /api/notifications/{id}/dismiss     clear one card
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from job_dashboard import notifications
from job_dashboard.db import init_db


class ReadBody(BaseModel):
    ids: Optional[list[int]] = None


def build_notification_router(db_path) -> APIRouter:
    router = APIRouter()

    def db():
        return init_db(db_path)

    @router.get("/api/notifications")
    def get_notifications(limit: int = 50):
        conn = db()
        try:
            return {"items": notifications.listing(conn, limit), "unread": notifications.unread(conn)}
        finally:
            conn.close()

    @router.post("/api/notifications/read")
    def read(body: ReadBody):
        conn = db()
        try:
            return {"marked": notifications.mark_read(conn, body.ids), "unread": notifications.unread(conn)}
        finally:
            conn.close()

    @router.post("/api/notifications/{notif_id}/dismiss")
    def dismiss(notif_id: int):
        conn = db()
        try:
            if not notifications.dismiss(conn, notif_id):
                raise HTTPException(status_code=404, detail="no such notification")
            return {"unread": notifications.unread(conn)}
        finally:
            conn.close()

    return router
