from career_agent.longform.needs import NEEDS, Plan
from career_agent.longform.recipes import RECIPES, retrieve


def ids(chunks):
    return [c.id for c in chunks]


def test_every_need_has_a_recipe():
    assert set(RECIPES) == set(NEEDS)


def test_intro_has_own_words_facts_and_a_card_for_every_project(kb):
    got = ids(retrieve(Plan(("intro",)), kb))
    assert {"story:story_how_you_work", "story:story_looking_for", "fact:current_title"} <= set(got)
    assert [i for i in got if i.startswith("card:")] == ["card:p-churn", "card:p-ocr", "card:p-graph", "card:p-portfolio"]
    assert not any(i.startswith(("project:", "source:")) for i in got)


def test_one_project_is_that_project_only(kb):
    got = ids(retrieve(Plan(("one_project",), "p-graph"), kb))
    assert got == ["project:p-graph:problem", "project:p-graph:hardest", "project:p-graph:result", "source:p-graph"]


def test_challenge_pulls_only_hardest_and_result(kb):
    assert ids(retrieve(Plan(("challenge",), "p-graph"), kb)) == [
        "project:p-graph:hardest", "project:p-graph:result", "source:p-graph"]


def test_why_company_mixes_goals_company_the_project_and_one_more_card(kb):
    got = ids(retrieve(Plan(("why_company",), "p-graph"), kb, question="q", jd_text="jd", company_text="Acme fights fraud"))
    assert got[:2] == ["story:story_looking_for", "story:story_why_startups"]
    assert "company" in got and "project:p-graph:result" in got
    cards = [i for i in got if i.startswith("card:")]
    assert len(cards) == 1 and cards != ["card:p-graph"]                    # a second project, as a one-liner only


def test_why_company_without_company_facts_falls_back_to_the_job_description(kb):
    got = ids(retrieve(Plan(("why_company",), "p-graph"), kb, jd_text="We build fraud tools"))
    assert "company" not in got and "jd" in got


def test_projects_overview_is_cards_only(kb):
    assert ids(retrieve(Plan(("projects_overview",)), kb)) == ["card:p-churn", "card:p-ocr", "card:p-graph", "card:p-portfolio"]


def test_simple_needs(kb):
    assert ids(retrieve(Plan(("looking_for",)), kb)) == ["story:story_looking_for", "story:story_problems"]
    assert ids(retrieve(Plan(("working_style",)), kb)) == ["story:story_how_you_work"]
    assert ids(retrieve(Plan(("skills_list",)), kb)) == ["skills:pool"]


def test_other_is_small_and_relevant(kb):
    got = retrieve(Plan(("other",)), kb, question="graph fraud detection experience")
    assert len(got) <= 4 and "card:p-graph" in ids(got)


def test_several_needs_dedupe_and_keep_order(kb):
    got = ids(retrieve(Plan(("intro", "looking_for")), kb))
    assert len(got) == len(set(got)) and got[0] == "story:story_how_you_work"


def test_budget_drops_from_the_end_but_keeps_the_first_chunk(kb):
    full = retrieve(Plan(("intro",)), kb)
    small = retrieve(Plan(("intro",)), kb, budget_chars=200)
    assert small[0].id == full[0].id and 1 <= len(small) < len(full)
    assert retrieve(Plan(("intro",)), kb, budget_chars=1)[0].id == full[0].id
