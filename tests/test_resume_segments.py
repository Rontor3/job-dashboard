from job_dashboard.resume.segments import load_segments, Segment


def test_loads_blocks_with_manifest_and_tex(tmp_path):
    (tmp_path / "a.tex").write_text(r"\section{Skills} Python, ML")
    (tmp_path / "segments.yaml").write_text(
        "segments:\n  - id: skills-core\n    kind: skills\n    title: Core Skills\n"
        "    tags: [python, ml]\n    tex: a.tex\n")
    segs = load_segments(tmp_path)
    assert len(segs) == 1
    s = segs[0]
    assert isinstance(s, Segment) and s.id == "skills-core"
    assert s.tags == ["python", "ml"]
    assert "Python, ML" in s.text


def test_missing_tex_file_raises_clear_error(tmp_path):
    (tmp_path / "segments.yaml").write_text(
        "segments:\n  - id: x\n    kind: skills\n    title: X\n    tags: []\n    tex: nope.tex\n")
    import pytest
    with pytest.raises(FileNotFoundError, match="nope.tex"):
        load_segments(tmp_path)


def test_real_segment_library_loads():
    segs = load_segments()
    assert len(segs) > 0
    for s in segs:
        assert isinstance(s, Segment)
        assert s.text.strip() != ""
