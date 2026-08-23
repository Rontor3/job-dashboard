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
