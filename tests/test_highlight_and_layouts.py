import re

from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.db import (
    init_db, save_resume_layout, get_resume_layout, list_resume_layouts,
    delete_resume_layout, WORKING_LAYOUT,
)
from job_dashboard.resume.resume_llm import highlight_bullets


def _strip_bold(s):
    return re.sub(r"\*\*", "", s)


def test_highlight_never_changes_wording():
    # LLM names phrases present in the text; a fabricated one ("Kubernetes")
    # must be ignored since it isn't in the bullet.
    fake = lambda _p: "AWS Lambda, API Gateway, Kubernetes"
    bullets = ["Productionized fraud scoring on AWS Lambda and API Gateway, saving 30% cost"]
    out = highlight_bullets(bullets, llm=fake)
    # words unchanged once bold markers are stripped
    assert _strip_bold(out[0]) == bullets[0]
    # real phrases + the metric got bolded
    assert "**AWS Lambda**" in out[0] and "**API Gateway**" in out[0]
    assert "**30%**" in out[0]
    # the fabricated term never appears
    assert "Kubernetes" not in out[0]


def test_highlight_safe_on_llm_failure():
    def boom(_p):
        raise RuntimeError("down")
    bullets = ["Built a pipeline saving 500 hours"]
    out = highlight_bullets(bullets, llm=boom)
    assert _strip_bold(out[0]) == bullets[0]  # still no wording change


def test_layout_roundtrip_and_versions(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    blocks = [{"kind": "experience", "title": "Tata AIG", "bullets": ["a", "b"]}]
    save_resume_layout(conn, WORKING_LAYOUT, blocks)
    assert get_resume_layout(conn, WORKING_LAYOUT)["layout"] == blocks

    save_resume_layout(conn, "v1-fintech", blocks)
    names = [v["name"] for v in list_resume_layouts(conn)]
    assert "v1-fintech" in names and WORKING_LAYOUT not in names  # working excluded

    delete_resume_layout(conn, "v1-fintech")
    assert [v["name"] for v in list_resume_layouts(conn)] == []


def test_layout_api(tmp_path):
    client = TestClient(create_app(db_path=str(tmp_path / "t.db")))
    blocks = [{"kind": "skills", "title": "Programming", "bullets": ["**Programming**: Python"]}]

    assert client.put("/api/resume/layout", json={"blocks": blocks}).status_code == 200
    got = client.get("/api/resume/layouts").json()
    assert got["working"] == blocks and got["versions"] == []

    assert client.post("/api/resume/layouts", json={"name": "Fintech v1", "blocks": blocks}).status_code == 200
    assert client.get("/api/resume/layouts/Fintech v1").json()["blocks"] == blocks
    # empty/reserved name rejected
    assert client.post("/api/resume/layouts", json={"name": "  ", "blocks": blocks}).status_code == 422
