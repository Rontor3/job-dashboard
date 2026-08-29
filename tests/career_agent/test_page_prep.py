from career_agent.browser.form_model import Field
from career_agent.browser.page_prep import suppress_noise


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
