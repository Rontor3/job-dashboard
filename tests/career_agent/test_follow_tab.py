"""A click that opens a new tab moves the run onto it, through the shared holder (LangGraph copies c per node)."""
from types import SimpleNamespace

from career_agent.orchestrator import graph


def _page(url, closed=False):
    return SimpleNamespace(url=url, is_closed=lambda: closed)


def test_follow_moves_the_run_to_the_new_tab():
    p1, p2 = _page("https://jobs.example/apply"), _page("https://login.example/taleo")
    c = {"page": p1, "tab": {"page": p1}}
    assert graph._follow(c, p1, SimpleNamespace(page=p2)) is p2
    c2 = dict(c)                                   # what LangGraph hands each node
    assert graph._page(c2) is p2
    assert c["tab"]["intended"] == p2.url


def test_follow_without_a_new_tab_stays_put():
    p1 = _page("https://jobs.example/apply")
    c = {"page": p1, "tab": {"page": p1}}
    assert graph._follow(c, p1, None) is p1
    assert graph._follow(c, p1, SimpleNamespace(page=p1)) is p1


def test_closed_tab_falls_back():
    p1, p2 = _page("https://jobs.example/apply"), _page("https://login.example/taleo", closed=True)
    c = {"page": p1, "tab": {"page": p2}}
    assert graph._page(c) is p1


def test_a_chat_page_stops_before_anything_is_filled(monkeypatch):
    # FedEx's Apply opened a chat-only page in a new tab: once followed, the run must hand it over, not answer the
    # chat box (or click its Send) as if it were a form
    from career_agent.browser import page_health, page_prep
    monkeypatch.setattr(page_health, "recover", lambda page, url: None)
    monkeypatch.setattr(page_prep, "says_already_applied", lambda page: False)
    monkeypatch.setattr(page_prep, "is_chat_apply", lambda page: True)
    chat = _page("https://chat.example/apply")
    cfg = {"configurable": {"page": _page("https://jobs.example/job/1"), "tab": {"page": chat}, "deps": None}}
    assert graph.perceive_node({"url": "https://jobs.example/job/1"}, cfg) == {"stopped_reason": "chatbot_apply"}
