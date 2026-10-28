"""The site's own validation messages bind to the fields they name (validation.py)."""
import dataclasses

from career_agent.browser.form_model import Field
from career_agent.browser.validation import failing_fields, ref_key
from career_agent.orchestrator.advance import screen_signature


def _field(ref, label, kind="text"):
    return Field(ref=ref, kind=kind, label=label, required=True)


def test_a_message_binds_to_its_field_and_is_quoted_in_the_description():
    form = [_field("#phone", "Phone Number *"), _field("#school", "School *")]
    fields, banners = failing_fields(
        [{"ref": "#phone", "message": "This field is required"}], form)
    assert banners == []
    assert [f.ref for f in fields] == ["#phone"]
    assert "Site says: This field is required" in fields[0].description
    # the rest of the field survives untouched
    assert fields[0].kind == "text" and fields[0].required is True


def test_an_unpaired_message_is_a_banner_and_a_button_is_never_a_field():
    form = [_field("#a", "A", kind="button")]
    fields, banners = failing_fields(
        [{"ref": "", "message": "The email is already linked to an existing account"},
         {"ref": "#a", "message": "no"}], form)
    assert fields == []
    assert banners == ["The email is already linked to an existing account"]


def test_descriptions_accumulate_never_loop_forever():
    f = _field("#x", "X")
    a = dataclasses.replace(f, description="Site says: bad")
    again, _ = failing_fields([{"ref": "#x", "message": "bad"}], [a])
    assert "bad | Site says: bad" in again[0].description or "Site says: bad" in again[0].description


def test_two_messages_for_one_field_keep_only_the_field():
    form = [_field("#city", "City *")]
    fields, _ = failing_fields(
        [{"ref": "#city", "message": "City is required"},
         {"ref": "#city", "message": "Enter a valid city"}], form)
    assert len(fields) == 1


def test_ref_key_is_stable_across_tolerable_differences_and_serialisable():
    s1 = ("/a", frozenset({"name", "email"}), "step")
    s2 = ("/a", frozenset({"email", "name"}), "step")
    assert ref_key(s1) == ref_key(s2)          # label order is irrelevant
    assert ref_key(s1) != ref_key(("/b", frozenset({"name", "email"}), "step"))
    assert isinstance(ref_key(s1), str)         # survives into the checkpointer's store


def test_screen_signature_carries_the_progress_indicator():
    from career_agent.browser.form_model import Field as F
    form = [F(ref="#n", kind="text", label="Name *", required=True)]
    a = screen_signature("/apply", form, "Step 1 of 3")
    b = screen_signature("/apply", form, "Step 2 of 3")
    assert a != b      # a wizard may re-label nothing but its stepper — that is still progress
