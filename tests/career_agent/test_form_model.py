from dataclasses import FrozenInstanceError

import pytest

from career_agent.browser.form_model import Field, guess_purpose


def test_field_is_frozen_dataclass():
    f = Field(ref="#a", kind="text", label="Full name", required=True)
    with pytest.raises(FrozenInstanceError):
        f.label = "Email"


def test_guess_common_purposes():
    assert guess_purpose("Full Name", "text") == "full_name"
    assert guess_purpose("Email address", "email") == "email"
    assert guess_purpose("Mobile number", "tel") == "phone"
    assert guess_purpose("LinkedIn Profile URL", "text") == "linkedin_url"
    assert guess_purpose("GitHub", "text") == "github_url"
    assert guess_purpose("Are you authorized to work in the US?", "select") == "work_authorization"
    assert guess_purpose("Notice period", "text") == "notice_period"
    assert guess_purpose("Expected salary", "text") == "salary_expectation"
    assert guess_purpose("Upload your resume", "file") == "resume_upload"


def test_postal_code_and_phone_extension_classified_distinctly():
    assert guess_purpose("Postal Code", "text") == "postal_code"
    assert guess_purpose("Zip Code", "text") == "postal_code"
    assert guess_purpose("Phone Number", "text") == "phone"
    assert guess_purpose("Phone Extension", "text") == "phone_extension"
    assert guess_purpose("Country Phone Code", "text") == "phone"


def test_attestation_detected_for_consent_checkbox():
    assert guess_purpose("I certify the above is true", "checkbox") == "attestation"
    assert guess_purpose("I consent to a background check", "checkbox") == "attestation"


def test_unknown_returns_none():
    assert guess_purpose("What is your favourite colour?", "text") is None


def test_essay_prompt_mentioning_experience_is_not_years_experience():
    """A long free-text prompt that merely uses the word "experience" must not
    be forced into the single short years_experience purpose — that overwrites
    an essay field with a bare number. Only "years of/years experience" phrasing
    should match."""
    assert guess_purpose(
        "A little bit about yourself. Talk about relevant experience you have "
        "in data and ML engineering.", "textarea") is None
    assert guess_purpose("Years of experience", "text") == "years_experience"


def test_graduation_year_precedes_bare_degree():
    """"Year of graduation from your undergrad degree" contains the word
    "degree" but asks for a YEAR, not the degree name — must not collide with
    the bare `degree` rule."""
    assert guess_purpose("Year of graduation from your undergrad degree.", "text") == "graduation_year"
    assert guess_purpose("Degree", "text") == "degree"
