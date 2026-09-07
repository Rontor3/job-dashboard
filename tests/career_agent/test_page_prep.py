from career_agent.browser.form_model import Field
from career_agent.browser.page_prep import suppress_noise, _best_apply


def _f(ref, label, kind="text", purpose=None):
    return Field(ref, kind, label, False, [], None, purpose)


def test_suppress_noise_drops_chatbot_honeypot_captcha():
    fields = [
        _f("#name", "Full name", purpose="full_name"),                    # keep
        _f("#oda-chat-user-text-input", "Ask Me Something"),              # chatbot -> drop
        _f('[name="oda-work-summary-text-area"]', "Add Summary"),        # chatbot -> drop
        _f('[name="honey-pot"]', ""),                                     # honeypot -> drop
        _f("#g-recaptcha-response", "g-recaptcha-response", kind="textarea"),  # token -> drop
        _f("#q", "Why do you want this role?", kind="textarea"),          # keep
    ]
    kept = {f.ref for f in suppress_noise(fields)}
    assert kept == {"#name", "#q"}


def test_best_apply_ranks_and_rejects():
    B = lambda n: {"name": n, "role": "button"}
    # highest-priority phrase wins over a bare "Apply"
    assert _best_apply([B("Apply"), B("Apply for this job")])["name"] == "Apply for this job"
    # deny terms are rejected even though they contain "apply"
    assert _best_apply([B("Apply filter"), B("Easy apply")]) is None
    # picks the real Apply out of search/save chrome (the eBay/SocGen/Swiggy case)
    cands = [B("Search"), B("Save job"), {"name": "Apply now", "role": "link"},
             B("Sign in"), B("Dark mode")]
    best = _best_apply(cands)
    assert best["name"] == "Apply now" and best["role"] == "link"
    # nothing to apply to -> None
    assert _best_apply([B("Search"), B("Save"), B("Subscribe")]) is None
    # over-long sentence containing 'apply' is not a button label
    assert _best_apply([B("By continuing you apply to the terms and conditions here")]) is None
