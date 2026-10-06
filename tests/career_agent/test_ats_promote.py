import json

from career_agent.memory.ats_promote import promote

RUN = """
## Run 2026-10-04T00:00:00Z
- URL: https://himalayas.app/companies/x/jobs/y?utm=1
- job_id: 1
- stopped_reason: {reason}
- filled: 11  escalated: 6
- submitted: False
- landed: jobs.lever.co/x/abc/apply
- trail: {trail}
"""
TRAIL = json.dumps([
    {"step": "hop", "click": "Apply now", "role": "button", "frame": 0, "url_before": "h/a", "url_after": "h/a"},
    {"step": "modal_kept", "why": "offers an apply control"},
    {"step": "hop", "click": "I'm ready to apply", "role": "link", "frame": 0, "url_before": "h/a", "url_after": "jobs.lever.co/x/abc/apply"},
    {"step": "reach_end", "status": "form", "url": "jobs.lever.co/x/abc/apply"}])


def test_promote_writes_site_node_and_moves_block(tmp_path):
    pend, graph = tmp_path / "pending_memory_updates.md", tmp_path / "g.json"
    graph.write_text(json.dumps({"nodes": [], "edges": []}))
    legacy = "\n## Run 2026-09-01T00:00:00Z\n- URL: https://old.example/x\n- stopped_reason: None\n"
    pend.write_text(legacy + RUN.format(reason="no_advance_control", trail=TRAIL)
                    + RUN.format(reason="None", trail=TRAIL))
    assert promote(pend, graph) == {"promoted": 2, "sites": ["site:himalayas.app"]}
    g = json.loads(graph.read_text())
    node = next(n for n in g["nodes"] if n["id"] == "site:himalayas.app")
    assert node["errors_seen"] == ["no_advance_control"]            # failure kept, not lost
    assert node["reach_path"][0].startswith("click button 'Apply now'")
    assert node["lands_on"] == "jobs.lever.co"
    assert {"from": "site:himalayas.app", "to": "site:jobs.lever.co", "rel": "ROUTES_TO"} in g["edges"]
    assert "old.example" in pend.read_text() and "himalayas" not in pend.read_text()   # legacy untouched
    assert "himalayas" in (tmp_path / "pending_memory_promoted.md").read_text()
    assert promote(pend, graph)["promoted"] == 0                     # idempotent


def test_site_hint_needs_learned_clicks(tmp_path, monkeypatch):
    from career_agent.browser import ats_lookup
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"nodes": [
        {"id": "site:a", "type": "site", "domains": ["a.example"], "reach_clicks": ["Apply now"]},
        {"id": "site:b", "type": "site", "domains": ["b.example"]}], "edges": []}))
    monkeypatch.setattr(ats_lookup, "_GRAPH", g)
    assert ats_lookup.site_hint("https://www.a.example/jobs/1")["id"] == "site:a"
    assert ats_lookup.site_hint("https://b.example/x") is None            # known site, nothing learned yet
    assert ats_lookup.site_hint("https://c.example/x") is None
