import builtins
from career_agent.integrations.approver import CliApprover, AutoDenyApprover


def test_cli_yes(monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda *_: "yes")
    assert CliApprover().request("CARD") is True
    assert "CARD" in capsys.readouterr().out


def test_cli_no(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *_: "n")
    assert CliApprover().request("CARD") is False


def test_auto_deny_is_false():
    assert AutoDenyApprover().request("anything") is False



def test_preset_collector_answers_by_label_and_defers_the_rest():
    from career_agent.browser.form_model import Field
    from career_agent.integrations.approver import PresetCollector
    asked = []

    class Inner:
        _last_events = {"b": "edit"}
        def __call__(self, fields):
            asked.extend(f.label for f in fields)
            return {f.ref: "typed" for f in fields}

    f = lambda ref, label: Field(ref, "text", label, True, [], None, None)
    c = PresetCollector({"years of work experience do you have with Python": "3",
                         "Is your current salary above USD 3500": "Yes"}, inner=Inner())
    out = c([f("a", "How many years of work experience do you have with Python (Programming Language)?*"),
             f("b", "Why do you want this job?"),
             f("c", "Is your Current Salary Above USD 3500?*")])
    assert out == {"a": "3", "b": "typed", "c": "Yes"}
    assert asked == ["Why do you want this job?"]
    assert c._last_events == {"a": "approve", "c": "approve", "b": "edit"}
