"""Work/education entry boxes are answered from that entry: Workday's bare 'Month'/'Year' got nothing or the bank's
'2023' for every year (Amgen, athenahealth, Pretium, Trinity, Opella; 2026-10-25)."""
from types import SimpleNamespace as N
from career_agent.orchestrator.entry_fields import entry_decisions

PROF = N(experiences=[N(start="July 2023", end="Present", bullets=["Built X", "Shipped Y"]),
                      N(start="May 2022", end="Jul 2022", bullets=["Tracker"])],
         education=[N(start="", end="")], contact={"education_start": "July 2019", "education_end": "May 2023"})


def F(ref, kind="text", label="Month"):
    return N(ref=ref, kind=kind, label=label, part_hint=ref.lstrip("#"))


def _vals(fields):
    ds, rest, _ = entry_decisions(fields, PROF)
    return {d.ref: d.value for d in ds}, [f.ref for f in rest]


def test_each_work_entry_gets_its_own_dates():
    got, _ = _vals([F("#workExperience-351--startDate-dateSectionMonth-input"),
                    F("#workExperience-351--startDate-dateSectionYear-input", label="Year"),
                    F("#workExperience-352--startDate-dateSectionYear-input", label="Year"),
                    F("#workExperience-352--endDate-dateSectionMonth-input")])
    assert list(got.values()) == ["07", "2023", "2022", "07"]


def test_the_current_jobs_end_date_is_left_out():
    got, rest = _vals([F("#workExperience-351--endDate-dateSectionMonth-input")])
    assert got == {} and rest == []


def test_role_description_is_that_entrys_bullets():
    got, _ = _vals([F("#workExperience-351--roleDescription", "textarea", "Role Description")])
    assert got == {"#workExperience-351--roleDescription": "• Built X\n• Shipped Y"}


def test_education_years_come_from_the_profile_dates():
    got, _ = _vals([F("#education-368--firstYearAttended-dateSectionYear-input", label="Year"),
                    F("#education-368--lastYearAttended-dateSectionYear-input", label="Year")])
    assert list(got.values()) == ["2019", "2023"]


def test_fields_outside_an_entry_are_untouched():
    got, rest = _vals([F("#email", label="Email"), F("#source--source", label="How Did You Hear")])
    assert got == {} and rest == ["#email", "#source--source"]


def test_role_description_drops_characters_workday_refuses():
    prof = N(experiences=[N(start="July 2023", end="Present", bullets=['ROC >85 on [claims] "fast"'])], education=[], contact={})
    ds, _, _ = entry_decisions([F("#workExperience-1--roleDescription", "textarea", "Role Description")], prof)
    assert not set('<>[]"{}\\') & set(ds[0].value) and "over 85" in ds[0].value


def test_role_description_drops_markdown_bold():
    prof = N(experiences=[N(start="July 2023", end="Present", bullets=["meeting **IRDAI** audit, **50%** overlap"])],
             education=[], contact={})
    ds, _, _ = entry_decisions([F("#workExperience-1--roleDescription", "textarea", "Role Description")], prof)
    assert "**" not in ds[0].value and "IRDAI" in ds[0].value
