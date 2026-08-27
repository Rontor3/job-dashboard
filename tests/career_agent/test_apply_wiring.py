def test_browser_deps_has_required_ops():
    from career_agent.orchestrator.browser_deps import BrowserDeps
    for op in ("snapshot", "gate", "fill", "click", "url"):
        assert hasattr(BrowserDeps, op)

def test_apply_main_importable():
    import career_agent.apply as a
    assert hasattr(a, "main")
