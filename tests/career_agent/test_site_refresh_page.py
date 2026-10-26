"""A site's own 'Something went wrong. Please refresh' step is reloaded, at most twice (Workday, 2026-10-26)."""
from career_agent.browser import page_health


class Page:
    def __init__(self, bodies):
        self.bodies, self.url, self.reloads = list(bodies), "https://x.myworkdayjobs.com/apply/step2", 0
    def evaluate(self, js): return self.bodies[0]
    def reload(self, wait_until=None):
        self.reloads += 1
        if len(self.bodies) > 1:
            self.bodies.pop(0)


def test_a_refresh_page_is_reloaded_and_recovers(monkeypatch):
    monkeypatch.setattr(page_health, "_TRIED", set())
    monkeypatch.setattr("career_agent.browser.clicks.wait_until_stable", lambda p: None)
    p = Page(["Something went wrong\\nPlease refresh the page and then try again.", "My Information  Save and Continue"])
    assert page_health.recover(p, p.url) == "recovered" and p.reloads == 1


def test_a_page_that_keeps_failing_is_dead_after_two_reloads(monkeypatch):
    monkeypatch.setattr(page_health, "_TRIED", set())
    monkeypatch.setattr("career_agent.browser.clicks.wait_until_stable", lambda p: None)
    p = Page(["Something went wrong. Please refresh the page and then try again."])
    page_health.recover(p, p.url)
    assert page_health.recover(p, p.url) == "dead" and p.reloads == 2


def test_a_healthy_page_is_left_alone(monkeypatch):
    monkeypatch.setattr(page_health, "_TRIED", set())
    p = Page(["Apply for this job"])
    assert page_health.recover(p, p.url) is None and p.reloads == 0
