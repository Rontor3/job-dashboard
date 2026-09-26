from fastapi.testclient import TestClient
from job_dashboard.api.app import create_app


def test_enable_switch_roundtrip(tmp_path):
    c = TestClient(create_app(str(tmp_path / "j.db"), pipeline_runner=lambda p, s: {}))
    assert c.get("/api/agent-settings").json()["browser_linkedin_enabled"] is False
    assert c.put("/api/agent-settings", json={"browser_linkedin_enabled": True}).status_code == 200
    assert c.get("/api/agent-settings").json()["browser_linkedin_enabled"] is True


def test_naukri_switch_roundtrip(tmp_path):
    c = TestClient(create_app(str(tmp_path / "j.db"), pipeline_runner=lambda p, s: {}))
    assert c.get("/api/agent-settings").json()["browser_naukri_enabled"] is False
    assert c.put("/api/agent-settings", json={"browser_naukri_enabled": True}).status_code == 200
    assert c.get("/api/agent-settings").json()["browser_naukri_enabled"] is True
    assert c.get("/api/agent-settings").json()["browser_linkedin_enabled"] is False


def test_new_site_switches_default_off_and_toggle(tmp_path):
    c = TestClient(create_app(str(tmp_path / "j.db"), pipeline_runner=lambda p, s: {}))
    for site in ("wellfound", "instahyre", "iimjobs"):
        key = f"browser_{site}_enabled"
        assert c.get("/api/agent-settings").json()[key] is False
        assert c.put("/api/agent-settings", json={key: True}).status_code == 200
        assert c.get("/api/agent-settings").json()[key] is True
