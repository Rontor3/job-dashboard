from job_dashboard.match.relevance import nuisance_match


def test_flags_obvious_offtarget_roles():
    assert nuisance_match("Associate Graphic Designer")
    assert nuisance_match("Assistant Professor in Computer Science")
    assert nuisance_match("Staff Nurse")
    assert nuisance_match("Sales Executive - North")
    assert nuisance_match("Talent Acquisition Specialist")


def test_does_not_flag_ds_ml_or_software_roles():
    for good in ["Senior Data Scientist", "Machine Learning Engineer",
                 "AI/ML Engineer", "Java Full Stack Developer", "Project Manager",
                 "Design Engineer", "Test Engineer", "Data Engineer",
                 "Forward Deployed Engineer"]:
        assert nuisance_match(good) is None, good


def test_word_boundary_no_substring_false_hit():
    # "designer" must not fire on "design engineer" / "designed"
    assert nuisance_match("Design Engineer") is None
    assert nuisance_match("Firmware Design Engineer") is None


def test_none_title_safe():
    assert nuisance_match(None) is None
    assert nuisance_match("") is None
