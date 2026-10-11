"""Dialogs over an application page: what kind each one is (browser/dialogs.py)."""
import pytest

from career_agent.browser.dialogs import DENY, classify

MERCOR_REFERRAL = {"label": "You've been referred!", "inputs": 1, "password": False,
                   "text": "You've been referred!\nYou'll be referred by Himalayas Team. If you don't recognize this person, "
                           "you can change the code or decline.\nReferral code", "buttons": ["Decline", "Yes"]}


@pytest.mark.parametrize("dialog, kind", [
    (MERCOR_REFERRAL, "question"),
    ({"label": "Login window", "text": "", "buttons": ["Close"]}, "login"),
    ({"label": "", "text": "Sign in to apply\nEmail", "buttons": ["Continue"], "inputs": 1}, "login"),
    ({"label": "", "text": "Password", "buttons": ["Next"], "password": True}, "login"),
    ({"label": "We use cookies", "text": "We use cookies to improve...", "buttons": ["Accept all", "Reject all"]}, "consent"),
    ({"label": "", "text": "Are you still there? Your session will expire in 2 minutes", "buttons": ["Continue Working"]}, "idle"),
    ({"label": "", "text": "Before you apply", "buttons": ["I'm ready to apply", "Cancel"]}, "apply_step"),
    ({"label": "", "text": "Please verify you are human", "buttons": []}, "captcha"),
])
def test_each_dialog_gets_its_kind(dialog, kind):
    assert classify(dialog) == kind


@pytest.mark.parametrize("button, refused", [("Decline", False), ("Yes", False), ("Close", False),
                                             ("Submit application", True), ("Sign up", True), ("Log in", True),
                                             ("Pay now", True), ("Delete", True)])
def test_submit_signin_and_payment_buttons_are_never_pressed_from_a_dialog(button, refused):
    assert bool(DENY.search(button)) is refused
