from job_dashboard.resume.resume_llm import generate_bullets


def test_grounding_strips_numbers_not_in_details():
    # LLM tries to inject a fabricated metric (40%) the user never typed,
    # and echoes one real number (500) that IS in the details.
    fake = lambda _p: (
        "- Built a fraud pipeline on AWS Lambda saving 500 hours/month\n"
        "- Boosted recall by 40% using nested XGBoost models\n"
        "- Deployed real-time scoring via API Gateway"
    )
    details = "fraud pipeline, AWS Lambda, nested models, saved 500 hours a month"
    out = generate_bullets("Health Fraud Pipeline", details, llm=fake, n=3)

    assert len(out) == 3
    joined = " ".join(out)
    assert "500" in joined                 # real number the user typed survives
    assert "40%" not in joined and "40 %" not in joined  # fabricated metric stripped
    # tech stack preserved
    assert "AWS Lambda" in joined and "API Gateway" in joined


def test_empty_details_returns_empty():
    assert generate_bullets("x", "   ", llm=lambda _p: "- anything") == []


def test_llm_failure_never_raises():
    def boom(_p):
        raise RuntimeError("ollama down")
    assert generate_bullets("x", "real notes here", llm=boom) == []


def test_caps_to_n_bullets():
    fake = lambda _p: "- a\n- b\n- c\n- d\n- e"
    assert len(generate_bullets("x", "notes", llm=fake, n=3)) == 3


def test_strips_ai_tells_and_keeps_meaning():
    # LLM emits classic AI phrasing; the cleaner must plain it out.
    fake = lambda _p: (
        "- Leveraged AWS Lambda to seamlessly build a robust fraud pipeline saving 500 hours\n"
        "- Successfully utilized DynamoDB in order to store data\n"
        "- Spearheaded a comprehensive rewrite — improving latency"
    )
    details = "aws lambda, dynamodb, fraud pipeline, saved 500 hours"
    out = generate_bullets("Fraud", details, llm=fake, n=3)
    joined = " ".join(out).lower()
    for banned in ["leverag", "seamlessly", "robust", "successfully",
                   "utiliz", "in order to", "spearhead", "comprehensive", "—"]:
        assert banned not in joined, f"AI tell survived: {banned}"
    # real content + number preserved
    assert "aws lambda" in joined and "500" in joined
