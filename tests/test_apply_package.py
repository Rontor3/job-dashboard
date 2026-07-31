from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing
from job_dashboard.apply.store import save_application_profile
from job_dashboard.apply.package import assemble_application_package


def _seed(tmp_path):
    c = init_db(str(tmp_path / "t.db"))
    insert_job(c, JobListing(source="s", title="ML Eng", company="Acme",
                             job_url="https://x/1", description="jd"))
    jid = c.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    return c, jid


def test_package_resume_only_when_no_cover_letter(tmp_path):
    c, jid = _seed(tmp_path)
    save_application_profile(c, {"full_name": "R", "email": "r@x.com"})
    pkg = assemble_application_package(c, jid)
    assert pkg["profile"]["full_name"] == "R"
    assert pkg["cover_letter"] is None          # optional, absent
    assert pkg["job"]["company"] == "Acme"


def test_package_includes_cover_letter_when_present(tmp_path):
    from job_dashboard.db import save_cover_letter
    c, jid = _seed(tmp_path)
    save_cover_letter(c, jid, "/tmp/cl.pdf", "Dear ...", [])
    pkg = assemble_application_package(c, jid)
    assert pkg["cover_letter"] is not None
    assert pkg["cover_letter"]["pdf_path"] == "/tmp/cl.pdf"


def test_package_tolerates_unset_profile(tmp_path):
    c, jid = _seed(tmp_path)
    pkg = assemble_application_package(c, jid)
    assert pkg["profile"] is None and pkg["job"]["company"] == "Acme"
