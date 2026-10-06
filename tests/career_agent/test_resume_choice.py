from career_agent.apply import supplied_resume_pdf
from career_agent.orchestrator.tailor_cv import tailor_cv_node


def test_the_resume_the_candidate_supplied_is_the_one_uploaded(tmp_path, monkeypatch):
    mine = tmp_path / "DS_Rakshit_Singh.pdf"; mine.write_bytes(b"%PDF-1.4")
    monkeypatch.setenv("CURRENT_RESUME_PDF", str(mine))
    assert supplied_resume_pdf() == str(mine)
    monkeypatch.setenv("CURRENT_RESUME_PDF", str(tmp_path / "missing.pdf"))
    assert supplied_resume_pdf() is None                       # nothing supplied: the caller falls back


def test_a_generated_tailored_resume_never_replaces_it_unless_asked(tmp_path):
    cfg = {"configurable": {"resume_pdf": "/mine.pdf", "resume_out_dir": str(tmp_path)}}
    state = {"jd_text": "We need a machine learning engineer with Python and AWS experience " * 3}
    assert tailor_cv_node(state, cfg) == {} and cfg["configurable"]["resume_pdf"] == "/mine.pdf"
    assert not any(tmp_path.iterdir())                         # nothing was rendered


def test_the_upload_is_a_copy_named_after_the_candidate_and_the_original_is_untouched(tmp_path, monkeypatch):
    mine = tmp_path / "current_resume.pdf"; mine.write_bytes(b"%PDF-1.4 mine")
    monkeypatch.setenv("CURRENT_RESUME_PDF", str(mine))
    out = supplied_resume_pdf(upload_name="Rakshit Singh", out_dir=tmp_path / "upload")
    assert out.endswith("Rakshit_Singh_Resume.pdf") and open(out, "rb").read() == b"%PDF-1.4 mine"
    assert mine.exists() and supplied_resume_pdf() == str(mine)
