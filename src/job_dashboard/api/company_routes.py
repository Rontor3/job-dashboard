"""Details that hold for every opening at a company (company_details.py), set once on the Jobs tab.

    GET /api/company-details              {companies: {key: {company, details}}}
    PUT /api/company-details              {company, details}: save (logged, with Undo); empty details clear it
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from job_dashboard import changes, company_details
from job_dashboard.db import init_db


class Details(BaseModel):
    referrer: str = Field(default="", max_length=120)
    relatives: bool = False
    applied_before: bool = False
    interviewed_before: bool = False
    worked_before: bool = False


class CompanyBody(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    details: Details


def build_company_router(db_path) -> APIRouter:
    router = APIRouter()

    def db():
        conn = init_db(db_path)
        company_details.ensure(conn)
        return conn

    @router.get("/api/company-details")
    def get_all():
        conn = db()
        try:
            return {"companies": company_details.every(conn)}
        finally:
            conn.close()

    @router.put("/api/company-details")
    def put_one(body: CompanyBody):
        details = {**body.details.model_dump(), "referrer": body.details.referrer.strip()}
        conn = db()
        try:
            changes.apply(conn, "company", body.company.strip(), "details", details)
            return {"company": body.company.strip(), "details": company_details.get(conn, body.company)}
        finally:
            conn.close()

    return router
