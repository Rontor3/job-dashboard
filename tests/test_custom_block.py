from job_dashboard.resume.custom_block import escape_tex, block_to_tex, segment_bullets


def test_escape_tex_specials():
    assert escape_tex("a & b 50% $x #1 _y {z}") == r"a \& b 50\% \$x \#1 \_y \{z\}"


def test_experience_block_is_items_escaped():
    tex = block_to_tex("experience", "DS at Acme", ["Cut cost 20%", "Shipped ML"])
    assert r"\item Cut cost 20\%" in tex
    assert r"\item Shipped ML" in tex


def test_project_and_skills_lead_with_bold_title():
    proj = block_to_tex("project", "RoamMate", ["AI travel app"])
    assert r"\item \textbf{RoamMate}" in proj
    skills = block_to_tex("skills", "GenAI / LLM", ["RAG", "LoRA"])
    assert r"\textbf{GenAI / LLM}" in skills and "RAG" in skills


def test_never_raises_on_odd_input():
    assert isinstance(block_to_tex("experience", None, [None, "", "ok"]), str)
    assert block_to_tex("skills", "x", []) == "" or "\\item" not in block_to_tex("skills", "x", [])


def test_segment_bullets_single_escaped_item_with_percent():
    """segment_bullets unescapes \\% to %."""
    bullets = segment_bullets(r"\item \textbf{RoamMate}: AI app with 19\% impact")
    assert len(bullets) == 1
    assert "RoamMate" in bullets[0]
    assert "19%" in bullets[0]
    assert "\\" not in bullets[0]


def test_segment_bullets_multiple_items():
    """segment_bullets splits on \\item and unescapes each."""
    tex = r"\item \textbf{Project}: First bullet" "\n" r"\item Second bullet"
    bullets = segment_bullets(tex)
    assert len(bullets) == 2
    assert "Project" in bullets[0] or "First bullet" in bullets[0]
    assert "Second bullet" in bullets[1]


def test_segment_bullets_empty_input():
    """segment_bullets returns empty list for empty input."""
    assert segment_bullets("") == []
    assert segment_bullets(None) == []


def test_segment_bullets_unescape_all_latex():
    """segment_bullets unescapes all LaTeX special chars."""
    tex = r"\item \&\%\$\#\_\{\}\textbackslash{}\textasciitilde{}\textasciicircum{}"
    bullets = segment_bullets(tex)
    assert len(bullets) == 1
    assert "&" in bullets[0]
    assert "%" in bullets[0]
    assert "$" in bullets[0]
    assert "#" in bullets[0]
    assert "_" in bullets[0]
    assert "{" in bullets[0]
    assert "}" in bullets[0]
    assert "\\" in bullets[0]
    assert "~" in bullets[0]
    assert "^" in bullets[0]


def test_segment_bullets_strips_textbf_colon_wrapper():
    """segment_bullets strips \\textbf{title}: wrapper."""
    tex = r"\item \textbf{Skills}: Python, Rust"
    bullets = segment_bullets(tex)
    assert len(bullets) == 1
    assert "Skills" in bullets[0] or "Python" in bullets[0]


def test_segment_bullets_strips_textbf_no_colon_wrapper():
    """segment_bullets strips \\textbf{title} wrapper without colon."""
    tex = r"\item \textbf{Title}"
    bullets = segment_bullets(tex)
    assert len(bullets) == 1
    assert "Title" in bullets[0]


def test_segment_bullets_collapses_whitespace():
    """segment_bullets collapses multiple spaces."""
    tex = r"\item   Multiple   spaces   here"
    bullets = segment_bullets(tex)
    assert len(bullets) == 1
    assert "  " not in bullets[0]


def test_segment_bullets_drops_empty():
    """segment_bullets skips empty items."""
    tex = r"\item First" "\n" r"\item " "\n" r"\item Second"
    bullets = segment_bullets(tex)
    assert len(bullets) == 2
    assert "First" in bullets[0]
    assert "Second" in bullets[1]


def test_segment_bullets_never_raises():
    """segment_bullets never raises on any input."""
    # These should not raise
    segment_bullets(None)
    segment_bullets("")
    segment_bullets(r"\item \textbf{\\\\\\}")
    segment_bullets(r"no items here")
    segment_bullets(r"\item" * 100)
