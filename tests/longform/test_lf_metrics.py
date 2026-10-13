import json

from career_agent.longform.kb import Chunk
from career_agent.longform.metrics import (average_precision, judge_relevance, required_items, score_answer,
                                           score_retrieval)

CH = [Chunk("a", "passage", "ClaimGuard uses Claude Vision.", "p"), Chunk("b", "passage", "Hobbies: chess.", "p"),
      Chunk("c", "passage", "Pydantic validates LLM output.", "p")]


def scripted(**replies):
    """A judge that answers by which task the prompt is."""
    def judge(prompt):
        for key, reply in replies.items():
            if key.replace("_", " ") in prompt:
                return json.dumps(reply)
        return "{}"
    return judge


def test_average_precision_rewards_relevant_passages_ranked_first():
    assert average_precision([True, True, False]) == 1.0
    assert average_precision([False, True, True]) == round((1 / 2 + 2 / 3) / 2, 4)
    assert average_precision([False, False]) == 0.0 and average_precision([]) is None


def test_an_ask_without_a_quote_from_the_question_is_dropped_as_invented():
    q = "Describe a project you shipped and what happened after launch."
    j = scripted(**{"List each separate thing": {"items": [
        {"item": "a past project", "kind": "own", "quote": "Describe a project you shipped"},
        {"item": "what happened", "kind": "own", "quote": "what happened after launch"},
        {"item": "integrate with a CRM", "kind": "general", "quote": "integrate with existing CRM systems"},
        {"item": "x", "kind": "bogus", "quote": "Describe a project"}]}})
    got = required_items(q, j)
    assert [i["item"] for i in got] == ["a past project", "what happened"]


def test_a_judge_that_returns_the_wrong_number_of_flags_is_rejected_not_guessed():
    assert judge_relevance("q", CH, scripted(**{"decide if it contains": {"judgments": [{"n": 1, "relevant": True}]}})) is None


def test_retrieval_scores_and_the_no_retrieval_question():
    items = [{"item": "a real LLM project", "kind": "own"}, {"item": "a standard method", "kind": "general"}]
    j = scripted(**{"decide if it contains": {"judgments": [{"n": 1, "relevant": True}, {"n": 2, "relevant": False}, {"n": 3, "relevant": True}]},
                    "contain the information needed": {"judgments": [{"n": 1, "supported": True}]}})
    s = score_retrieval("q", CH, j, items=items)
    assert s["needs_retrieval"] and s["contextual_relevancy"] == round(2 / 3, 4)
    assert s["contextual_recall"] == 1.0 and s["contextual_precision"] == round((1 + 2 / 3) / 2, 4)
    general_only = score_retrieval("q", CH, j, items=[{"item": "a plan", "kind": "general"}])
    assert general_only["needs_retrieval"] is False and general_only["contextual_recall"] is None   # recall n/a, not a zero


def test_answer_scores_and_a_claim_free_answer_is_faithful():
    items = [{"item": "a", "kind": "own"}, {"item": "b", "kind": "general"}]
    j = scripted(**{"the ANSWER addresses it directly": {"judgments": [{"n": 1, "addressed": True}, {"n": 2, "addressed": False}]}, "factual claim": {"claims": []}})
    s = score_answer("q", "I would do X.", CH, j, items=items)
    assert s["answer_relevancy"] == 0.5 and s["faithfulness"] == 1.0
