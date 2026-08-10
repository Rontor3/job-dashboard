from fastapi.testclient import TestClient

from job_dashboard.db import init_db, save_resume_block, list_resume_blocks, delete_resume_block
from job_dashboard.api.app import create_app


def test_store_roundtrip_and_upsert(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    bid = save_resume_block(conn, "project", "Offline RAG", ["Built a RAG system"])
    blocks = list_resume_blocks(conn)
    assert len(blocks) == 1 and blocks[0]["title"] == "Offline RAG"
    assert blocks[0]["bullets"] == ["Built a RAG system"]

    # same kind+title upserts (no duplicate row), bullets replaced
    save_resume_block(conn, "project", "Offline RAG", ["Rewrote with new metrics"])
    blocks = list_resume_blocks(conn)
    assert len(blocks) == 1 and blocks[0]["bullets"] == ["Rewrote with new metrics"]

    delete_resume_block(conn, bid)
    assert list_resume_blocks(conn) == []


def test_blocks_api_persist_and_list(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"))
    client = TestClient(app)

    r = client.post("/api/resume/blocks",
                    json={"kind": "skills", "title": "Leadership",
                          "bullets": ["Led a team of 5 engineers"]})
    assert r.status_code == 200 and r.json()["title"] == "Leadership"

    listed = client.get("/api/resume/blocks").json()["blocks"]
    assert any(b["title"] == "Leadership" for b in listed)

    bid = listed[0]["id"]
    assert client.delete(f"/api/resume/blocks/{bid}").status_code == 200
    assert client.get("/api/resume/blocks").json()["blocks"] == []


def test_blocks_api_validates(tmp_path):
    client = TestClient(create_app(db_path=str(tmp_path / "t.db")))
    assert client.post("/api/resume/blocks",
                       json={"kind": "bogus", "title": "x", "bullets": ["y"]}).status_code == 422
    assert client.post("/api/resume/blocks",
                       json={"kind": "skills", "title": "  ", "bullets": []}).status_code == 422
