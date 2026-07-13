from job_dashboard import source_registry as sources


def test_job_sources_returns_noarg_callables_without_network(monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "fetch_jobspy_jobs", lambda *a, **k: calls.append("jobspy") or [])
    monkeypatch.setattr(sources, "fetch_remotive_jobs", lambda *a, **k: calls.append("remotive") or [])
    monkeypatch.setattr(sources, "fetch_remoteok_jobs", lambda *a, **k: calls.append("remoteok") or [])
    monkeypatch.setattr(sources, "fetch_wwr_jobs", lambda *a, **k: calls.append("wwr") or [])
    monkeypatch.setattr(sources, "fetch_himalayas_jobs", lambda *a, **k: calls.append("himalayas") or [])

    fetchers = sources.job_sources()
    assert len(fetchers) >= 5
    for fetch in fetchers:
        assert fetch() == []
    assert {"jobspy", "remotive", "remoteok", "wwr", "himalayas"} <= set(calls)


def test_company_sources_wraps_startup_sheet(monkeypatch):
    monkeypatch.setattr(sources, "fetch_funded_startups", lambda: ["co"])
    fetchers = sources.company_sources()
    assert len(fetchers) == 1
    assert fetchers[0]() == ["co"]
