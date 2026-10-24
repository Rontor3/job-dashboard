"""Fallback launch hides automation tells; falls back to bundled Chromium when Chrome is missing."""
from types import SimpleNamespace

import playwright.sync_api

from career_agent.browser import runner


def _fake_pw(fail_chrome):
    calls = []

    def launch_persistent_context(user_data_dir, **kw):
        calls.append(kw)
        if fail_chrome and kw.get("channel") == "chrome":
            raise RuntimeError("chrome not installed")
        return SimpleNamespace(pages=["page"])

    pw = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch_persistent_context))
    return pw, calls


def _launch(monkeypatch, tmp_path, fail_chrome):
    pw, calls = _fake_pw(fail_chrome)
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: SimpleNamespace(start=lambda: pw))
    settings = SimpleNamespace(user_data_dir=str(tmp_path / "profile"), headed=True)
    _, _, page, browser = runner.launch(settings)
    return calls, page, browser


def test_launch_uses_chrome_without_automation_flags(monkeypatch, tmp_path):
    calls, page, browser = _launch(monkeypatch, tmp_path, fail_chrome=False)
    assert len(calls) == 1 and calls[0]["channel"] == "chrome"
    assert "--disable-blink-features=AutomationControlled" in calls[0]["args"]
    assert calls[0]["ignore_default_args"] == ["--enable-automation"]
    assert calls[0]["headless"] is False and page == "page" and browser is None


def test_launch_falls_back_to_bundled_chromium_with_same_flags(monkeypatch, tmp_path):
    calls, _, _ = _launch(monkeypatch, tmp_path, fail_chrome=True)
    assert len(calls) == 2 and "channel" not in calls[1]
    assert "--disable-blink-features=AutomationControlled" in calls[1]["args"]
