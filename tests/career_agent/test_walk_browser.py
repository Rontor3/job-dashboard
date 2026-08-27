import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1",
                                reason="set RUN_BROWSER_TESTS=1 to run")

def _url(name):
    return (Path(__file__).parent / "fixtures" / name).resolve().as_uri()

def test_walks_fixture_flow_and_submits():
    from playwright.sync_api import sync_playwright
    from career_agent.orchestrator.browser_deps import BrowserDeps
    from career_agent.orchestrator.step_engine import walk
    from career_agent.memory.candidate_profile import CandidateProfile, Experience

    prof = CandidateProfile(contact={"full_name": "Rakshit"},
                            experiences=[Experience("Tata AIG", "Data Scientist")])
    class Human:
        def approve(self, card): return True
        def remote_solve(self, p, g, o): return True
        def collect(self, fields): return {}
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.goto(_url("apply_step1.html"))
        out = walk(page, prof, Human(), BrowserDeps(), do_submit=True, autonomous=True)
        landed = page.url
        b.close()
    assert out["submitted"] is True
    assert landed.endswith("apply_done.html")
