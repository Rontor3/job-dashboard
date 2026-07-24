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


def test_exclusive_group_loaded():
    """Verify exclusive_group field is loaded correctly."""
    segs = load_segments()

    # Find Tata AIG segments
    tata_aig_ids = [
        "experience-tata-aig-full",
        "experience-tata-aig-etf",
        "experience-tata-aig-sto",
        "project-fraud-pipeline",
    ]

    tata_aig_segs = {s.id: s for s in segs if s.id in tata_aig_ids}

    # Verify all 4 Tata AIG segments have exclusive_group set to "tata-aig"
    for seg_id in tata_aig_ids:
        seg = tata_aig_segs[seg_id]
        assert seg.exclusive_group == "tata-aig", (
            f"{seg_id} should have exclusive_group='tata-aig', got {seg.exclusive_group}"
        )

    # Verify a non-Tata AIG segment has exclusive_group=None
    other_segs = {s.id: s for s in segs if s.id not in tata_aig_ids}
    assert len(other_segs) > 0, "Should have segments without exclusive_group"

    for seg in list(other_segs.values())[:3]:  # Check first 3
        assert seg.exclusive_group is None, (
            f"{seg.id} should have exclusive_group=None, got {seg.exclusive_group}"
        )
