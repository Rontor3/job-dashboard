"""The Inbox's updates feed, and what the agent has learned about the user.

    GET  /api/notifications                  {items, unread}: newest first, dismissed ones left out
    POST /api/notifications                  {title, body?, level?, job_id?, job_ids?}: the agent asks for attention
    POST /api/notifications/read             {ids?}: mark these (or all) read
    POST /api/notifications/{id}/dismiss     clear one card
    GET  /api/about-me                       {exists, text, sections}: data/agent/about-me.md, parsed by section
    PUT  /api/about-me                       {text}: replace it (logged, with Undo)
    POST /api/about-me/facts                 {section, fact, replaces?}: add one fact, or reword one (logged, with Undo)

about-me.md is the agent's memory across sessions: the target job, preferences, constraints, background and how the
user likes to work, in the user's own terms. Every session reads it, the user can edit it on the Memory tab, and
every change goes through the change log like any other write.
"""
from __future__ import annotations

import re
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from job_dashboard import change_entities, changes, notifications
from job_dashboard.db import init_db

SECTIONS = ("Target", "Preferences", "Constraints", "Background", "Working style", "Other")
TEMPLATE = ("# About me\n\nWhat the job agent has learned about me. Every agent session reads this; edit anything "
            "that's wrong.\n\n" + "\n\n".join(f"## {s}" for s in SECTIONS) + "\n")
_LOCK = threading.Lock()


class NotifyBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: Optional[str] = Field(default=None, max_length=2000)
    level: str = "info"
    job_id: Optional[int] = None
    job_ids: Optional[list[int]] = Field(default=None, max_length=100)


class ReadBody(BaseModel):
    ids: Optional[list[int]] = None


class AboutText(BaseModel):
    text: str = Field(max_length=40_000)


class Fact(BaseModel):
    section: str
    fact: str = Field(min_length=2, max_length=500)
    replaces: Optional[str] = Field(default=None, max_length=500)


def parse(text: str) -> dict[str, list[str]]:
    """{section: [fact, …]} from the `## Section` / `- fact` shape (anything else is kept in the text, not here)."""
    out: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            out.setdefault(current, [])
        elif current and re.match(r"^\s*[-*] ", line):
            out[current].append(re.sub(r"^\s*[-*] ", "", line).strip())
    return out


def add_fact(text: str, section: str, fact: str, replaces: str | None = None) -> tuple[str, bool]:
    """The text with ``fact`` under ``## section`` (or in place of the bullet ``replaces``). False if nothing changed."""
    fact = " ".join(fact.split())
    lines = text.rstrip("\n").split("\n")
    if replaces:
        target = " ".join(replaces.split()).lower()
        for i, line in enumerate(lines):
            if re.match(r"^\s*[-*] ", line) and " ".join(re.sub(r"^\s*[-*] ", "", line).split()).lower() == target:
                lines[i] = f"- {fact}"
                return "\n".join(lines) + "\n", True
        raise KeyError(replaces)
    if any(" ".join(re.sub(r"^\s*[-*] ", "", l).split()).lower() == fact.lower() for l in lines if re.match(r"^\s*[-*] ", l)):
        return text, False
    head = next((i for i, l in enumerate(lines) if l.strip() == f"## {section}"), None)
    if head is None:
        lines += ["", f"## {section}", f"- {fact}"]
    else:
        end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        while end > head + 1 and not lines[end - 1].strip():
            end -= 1
        lines.insert(end, f"- {fact}")
    return "\n".join(lines) + "\n", True


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

    @router.post("/api/notifications")
    def post_notification(body: NotifyBody):
        if body.level not in notifications.LEVELS:
            raise HTTPException(status_code=422, detail=f"level must be one of {', '.join(notifications.LEVELS)}")
        conn = db()
        try:
            data = {"job_ids": body.job_ids} if body.job_ids else None
            nid = notifications.notify(conn, "agent", body.title, body.body, level=body.level, job_id=body.job_id,
                                       data=data, source="agent")
            return {"id": nid}
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
            return {"dismissed": notif_id, "unread": notifications.unread(conn)}
        finally:
            conn.close()

    def about() -> dict:
        text = change_entities.read_file("about_me")
        return {"exists": text is not None, "text": text or TEMPLATE, "sections": parse(text or TEMPLATE),
                "known_sections": list(SECTIONS)}

    @router.get("/api/about-me")
    def get_about():
        return about()

    @router.put("/api/about-me")
    def put_about(body: AboutText):
        with _LOCK:
            conn = db()
            try:
                changes.apply(conn, "file", "about_me", "text", body.text)
            finally:
                conn.close()
        return about()

    @router.post("/api/about-me/facts")
    def post_fact(body: Fact):
        if body.section not in SECTIONS and not body.replaces:      # rewording keeps the fact where it is
            raise HTTPException(status_code=422, detail=f"section must be one of {', '.join(SECTIONS)}")
        with _LOCK:
            text = change_entities.read_file("about_me") or TEMPLATE
            try:
                new, changed = add_fact(text, body.section, body.fact, body.replaces)
            except KeyError:
                raise HTTPException(status_code=404, detail="no fact with that wording to replace; call get_about_me")
            if changed:
                conn = db()
                try:
                    changes.apply(conn, "file", "about_me", "text", new)
                finally:
                    conn.close()
        return {**about(), "changed": changed}

    return router
