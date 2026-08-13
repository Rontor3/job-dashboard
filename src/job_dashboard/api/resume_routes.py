"""Resume API endpoints: block manifest, suggest/generate, per-job resume
list, and PDF serving. Kept as its own ``APIRouter`` (not inline in
``app.py``) to respect the 500-line cap; ``create_app`` includes this
router.
"""
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from job_dashboard.db import (
    get_resume, init_db, job_detail, resumes_for_job,
    save_resume_block, list_resume_blocks, delete_resume_block,
    save_resume_layout, get_resume_layout, list_resume_layouts,
    delete_resume_layout, WORKING_LAYOUT,
)
from job_dashboard.match.profile_text import compose_profile_text
from job_dashboard.resume.ats import ats_check
from job_dashboard.resume.custom_block import segment_bullets
from job_dashboard.resume.engine import generate_resume, suggest_blocks
from job_dashboard.resume.fit import fit_to_page
from job_dashboard.resume.keyword_map import (
    GapKeyword, Rephrasing, extract_keywords, simple_deep_rank,
)
from job_dashboard.resume.render import render_pdf
from job_dashboard.resume.resume_llm import (
    extract_jd_keywords, generate_bullets, highlight_bullets, make_ollama_llm,
    regenerate_block, suggest_skills,
)
from job_dashboard.resume.segments import load_segments


class ResumeGenerateRequest(BaseModel):
    block_ids: list[str] = []  # optional: a layout-only request needs no block_ids
    accepted_rephrasings: list[dict] = []
    layout: list[dict] | None = None


class RegenerateBlockRequest(BaseModel):
    kind: str
    title: str
    bullets: list[str]


class SaveBlockRequest(BaseModel):
    kind: str
    title: str
    bullets: list[str]


class GenerateBulletsRequest(BaseModel):
    heading: str = ""
    details: str
    n: int = 3


class SuggestSkillsRequest(BaseModel):
    context: str          # the candidate's own experience + project text
    existing: list[str] = []  # skills already listed (to skip)


class HighlightRequest(BaseModel):
    bullets: list[str]


class SaveLayoutRequest(BaseModel):
    name: str = WORKING_LAYOUT  # default = the auto-saved working copy
    blocks: list[dict] = []


def build_resume_router(
    db_path, resume_engine=None, resume_llm=None, jd_keyword_extractor=None,
    bullet_llm=None,
) -> APIRouter:
    router = APIRouter()
    default_resume_llm = resume_llm if resume_llm is not None else make_ollama_llm()
    default_jd_keyword_extractor = (
        jd_keyword_extractor if jd_keyword_extractor is not None else extract_jd_keywords
    )

    @contextmanager
    def db():
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    @router.get("/api/resume/segments")
    def list_segments():
        """Return block manifest (id, kind, title, tags, exclusive_group, bullets)."""
        segments = load_segments()
        return {
            "segments": [
                {
                    "id": s.id,
                    "kind": s.kind,
                    "title": s.title,
                    "tags": s.tags,
                    "exclusive_group": s.exclusive_group,
                    "default": s.default,
                    "group": s.group,
                    "role_header": s.role_header,
                    "bullets": segment_bullets(s.text),
                }
                for s in segments
            ]
        }

    @router.get("/api/resume/blocks")
    def get_saved_blocks():
        """User-saved reusable blocks — merged into the editor on every job."""
        with db() as conn:
            return {"blocks": list_resume_blocks(conn)}

    @router.post("/api/resume/blocks")
    def save_block(body: SaveBlockRequest):
        """Persist a block to the reusable library (upsert on kind+title)."""
        if body.kind not in ("skills", "experience", "project"):
            raise HTTPException(status_code=422, detail="kind must be skills/experience/project")
        if not body.title.strip() or not body.bullets:
            raise HTTPException(status_code=422, detail="title and bullets required")
        with db() as conn:
            block_id = save_resume_block(conn, body.kind, body.title.strip(), body.bullets)
            return {"id": block_id, "kind": body.kind, "title": body.title.strip(),
                    "bullets": body.bullets}

    @router.delete("/api/resume/blocks/{block_id}")
    def remove_saved_block(block_id: int):
        with db() as conn:
            delete_resume_block(conn, block_id)
        return {"ok": True}

    @router.post("/api/resume/bullets")
    def make_bullets(body: GenerateBulletsRequest):
        """Turn a heading + rough details into 3 grounded resume bullets.
        Uses only numbers present in ``details`` (no fabrication). Never
        500s on LLM issues — ``generate_bullets`` returns ``[]`` safely."""
        if not body.details.strip():
            raise HTTPException(status_code=422, detail="details required")
        n = max(1, min(5, body.n))
        bullets = generate_bullets(body.heading, body.details, llm=bullet_llm, n=n)
        return {"bullets": bullets}

    @router.post("/api/resume/suggest-skills")
    def suggest_missing_skills(body: SuggestSkillsRequest):
        """Suggest skills the candidate demonstrably used in their own
        experience/projects but hasn't listed. Grounded (never invents);
        returns [] safely on any LLM issue."""
        if not body.context.strip():
            return {"skills": []}
        skills = suggest_skills(body.context, body.existing, llm=bullet_llm)
        return {"skills": skills}

    @router.post("/api/resume/highlight")
    def highlight(body: HighlightRequest):
        """Bold technical keywords + impact metrics in the given bullets
        WITHOUT changing wording. Safe on any LLM issue."""
        return {"bullets": highlight_bullets(body.bullets, llm=bullet_llm)}

    # --- Persisted résumé layouts: auto-saved working copy + named versions ---

    @router.get("/api/resume/layouts")
    def get_layouts():
        """The auto-saved working résumé plus the list of named versions."""
        with db() as conn:
            working = get_resume_layout(conn, WORKING_LAYOUT)
            return {
                "working": working["layout"] if working else None,
                "versions": list_resume_layouts(conn),
            }

    @router.put("/api/resume/layout")
    def put_working_layout(body: SaveLayoutRequest):
        """Auto-save the working résumé (called as the user edits)."""
        with db() as conn:
            save_resume_layout(conn, WORKING_LAYOUT, body.blocks)
        return {"ok": True}

    @router.post("/api/resume/layouts")
    def save_named_version(body: SaveLayoutRequest):
        """Save the current blocks as a named version."""
        name = body.name.strip()
        if not name or name == WORKING_LAYOUT:
            raise HTTPException(status_code=422, detail="a version name is required")
        with db() as conn:
            save_resume_layout(conn, name, body.blocks)
        return {"ok": True, "name": name}

    @router.get("/api/resume/layouts/{name}")
    def load_layout(name: str):
        """Load a named version's blocks."""
        with db() as conn:
            layout = get_resume_layout(conn, name)
        if layout is None:
            raise HTTPException(status_code=404, detail="version not found")
        return {"name": layout["name"], "blocks": layout["layout"]}

    @router.delete("/api/resume/layouts/{name}")
    def remove_layout(name: str):
        with db() as conn:
            delete_resume_layout(conn, name)
        return {"ok": True}

    @router.post("/api/jobs/{job_id}/resume/suggest")
    def suggest_resume(job_id: int):
        """Suggest resume blocks for a job."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")

        if resume_engine is None:
            segments = load_segments()
            jd_text = detail["description"]

            # Rephrasing keyword source: clean JD tech keywords from a
            # single LLM extraction call (e.g. "kubernetes", "pytorch"),
            # cross-referenced against the resume's own text so the LLM
            # isn't asked to reword blocks that already truthfully cover a
            # term. Deliberately NOT the stored deep-rank gaps below —
            # those are narrative fit-gap text ("5+ years required...")
            # meant for human display, not clean single-term keywords a
            # rephrasing prompt can act on.
            try:
                extracted_keywords = default_jd_keyword_extractor(jd_text) or []
            except Exception:
                # Defensive: extract_jd_keywords itself never raises, but an
                # injected/alternate extractor might (e.g. simulating
                # Ollama down) — treat that the same as "extraction
                # unavailable" rather than letting it 500 the endpoint.
                extracted_keywords = []
            if extracted_keywords:
                covered = set()
                for seg in segments:
                    covered |= set(extract_keywords(seg.text))
                rephrasing_keywords = [
                    kw for kw in extracted_keywords if kw.lower() not in covered
                ]
            else:
                # Extraction unavailable (e.g. Ollama down) -> fall back to
                # crude JD tokenization, same as before this fix.
                rephrasing_keywords = None

            result = suggest_blocks(
                segments, jd_text, simple_deep_rank,
                llm=default_resume_llm,
                keywords=rephrasing_keywords or None,
            )

            # Displayed gap chips are the stored deep-rank narrative gaps
            # (from /rank's record_llm_evaluation) when present — real
            # fit-gap feedback for a human, kept separate from the
            # extracted keywords driving rephrasing above. Falls back to
            # the engine's own JD-tokenization-based gap computation when
            # nothing is stored (unchanged prior behavior).
            stored_gaps = detail.get("gaps") or []
            if stored_gaps:
                result["gaps"] = [GapKeyword(jd_keyword=g) for g in stored_gaps]
        else:
            result = resume_engine.suggest_blocks(
                detail["description"], job_id
            )

        return result

    @router.post("/api/jobs/{job_id}/resume/generate")
    def generate_job_resume(job_id: int, body: ResumeGenerateRequest):
        """Generate a tailored resume PDF."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")

        if resume_engine is None:
            segments = load_segments()
            # Parse accepted rephrasings from request
            accepted_rephrasings = []
            for r in body.accepted_rephrasings:
                accepted_rephrasings.append(
                    Rephrasing(
                        block_id=r.get("block_id"),
                        original_text=r.get("original_text", ""),
                        proposed_text=r.get("proposed_text", ""),
                        jd_keyword=r.get("jd_keyword", ""),
                        confidence=r.get("confidence", "equivalent"),
                        needs_interview_prep=r.get("needs_interview_prep", False),
                    )
                )

            out_dir = Path(db_path).parent / "resumes"
            out_dir.mkdir(parents=True, exist_ok=True)

            try:
                with db() as conn:
                    result = generate_resume(
                        conn,
                        job_id,
                        body.block_ids,
                        accepted_rephrasings,
                        segments=segments,
                        jd_text=detail["description"],
                        render_pdf=render_pdf,
                        ats_check=ats_check,
                        fit_to_page=fit_to_page,
                        out_dir=out_dir,
                        layout=body.layout,
                    )
            except RuntimeError as e:
                if "lualatex not found" in str(e):
                    raise HTTPException(
                        status_code=503,
                        detail="install MacTeX — lualatex not found",
                    )
                raise
            except ValueError as exc:
                # Bad user input (e.g. a `layout` entry referencing an
                # unknown segment_id — see engine._resolve_layout) -> 422,
                # not a 500. Same convention as app.py's patch_status.
                raise HTTPException(status_code=422, detail=str(exc))

            # Convert ats_report to dict if it's a dataclass
            ats_report_dict = result["ats_report"]
            if hasattr(result["ats_report"], "__dataclass_fields__"):
                ats_report_dict = asdict(result["ats_report"])

            return {
                "resume_id": result["resume_id"],
                "pdf_url": f"/api/resumes/{result['resume_id']}/pdf",
                "ats_report": ats_report_dict,
                "blocks_used": result["blocks_used"],
                "cut_lines": result["cut_lines"],
                "interview_prep": result["interview_prep"],
            }
        else:
            try:
                result = resume_engine.generate_resume(
                    job_id, body.block_ids, body.accepted_rephrasings
                )
            except RuntimeError as e:
                if "lualatex not found" in str(e):
                    raise HTTPException(
                        status_code=503,
                        detail="install MacTeX — lualatex not found",
                    )
                raise
            return result

    @router.post("/api/jobs/{job_id}/resume/regenerate-block")
    def regenerate_resume_block(job_id: int, body: RegenerateBlockRequest):
        """Regenerate alternative phrasings for one resume block. Never
        500s on LLM issues — ``regenerate_block`` already returns ``[]``
        safely on any failure (unreachable Ollama, malformed output, etc)."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")

        if resume_engine is None:
            jd_text = detail["description"]
            try:
                profile_text = compose_profile_text().text
            except Exception:
                # Missing/empty candidate profile file -> regenerate with no
                # profile context rather than 500ing; regenerate_block
                # tolerates "" (same seam as letter_routes/apply_routes).
                profile_text = ""
            alternatives = regenerate_block(
                body.kind, body.title, body.bullets, jd_text, profile_text,
            )
        else:
            alternatives = resume_engine.regenerate_block(
                job_id, body.kind, body.title, body.bullets
            )

        return {"alternatives": alternatives}

    @router.get("/api/jobs/{job_id}/resumes")
    def list_job_resumes(job_id: int):
        """Get all resumes for a job."""
        with db() as conn:
            detail = job_detail(conn, job_id)
            if detail is None:
                raise HTTPException(status_code=404, detail="job not found")
            resumes = resumes_for_job(conn, job_id)
        return {"resumes": resumes}

    @router.get("/api/resumes/{resume_id}/pdf")
    def get_resume_pdf(resume_id: int):
        """Serve a resume PDF."""
        with db() as conn:
            resume = get_resume(conn, resume_id)
        if resume is None or not resume.get("pdf_path"):
            raise HTTPException(status_code=404, detail="resume not found")

        pdf_path = Path(resume["pdf_path"])
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF file not found")

        return FileResponse(pdf_path, media_type="application/pdf")

    return router
