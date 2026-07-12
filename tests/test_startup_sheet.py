from job_dashboard.sources import startup_sheet
from tests.conftest import FakeResponse

SAMPLE_CSV = (
    '"Company","Money Raised","Round","Month (2026)","Sector","HQ","Founders"\n'
    '"Anthropic","$50B","Series H","May","AI","San Francisco, CA","Dario Amodei"\n'
    '"","","","","","",""\n'
)


def test_fetch_funded_startups_parses_csv_and_skips_blank_rows(monkeypatch):
    monkeypatch.setattr(
        startup_sheet.requests, "get", lambda *a, **k: FakeResponse(text=SAMPLE_CSV)
    )

    companies = startup_sheet.fetch_funded_startups()

    assert len(companies) == 1
    assert companies[0].name == "Anthropic"
    assert companies[0].funding_amount == "$50B"
    assert companies[0].sector == "AI"
    assert companies[0].source == "startup_sheet"
