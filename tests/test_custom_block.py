from job_dashboard.resume.custom_block import escape_tex, block_to_tex


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
