from career_agent.browser.form_model import Field
from career_agent.browser.page_prep import suppress_noise, _best_apply, _is_ad_frame, login_from_signals, site_key


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
    assert _best_apply([B("Apply filter")]) is None
    # picks the real Apply out of search/save chrome (the eBay/SocGen/Swiggy case)
    cands = [B("Search"), B("Save job"), {"name": "Apply now", "role": "link"},
             B("Sign in"), B("Dark mode")]
    best = _best_apply(cands)
    assert best["name"] == "Apply now" and best["role"] == "link"
    # nothing to apply to -> None
    assert _best_apply([B("Search"), B("Save"), B("Subscribe")]) is None


def test_ready_to_apply_beats_an_ads_apply_now():
    B = lambda n: {"name": n, "role": "button"}
    assert _best_apply([B("Apply Now"), B("I'm ready to apply")])["name"] == "I'm ready to apply"


def test_is_ad_frame():
    assert _is_ad_frame("https://googleads.g.doubleclick.net/pagead/ads?x=1")
    assert _is_ad_frame("about:blank", title="Advertisement")
    assert _is_ad_frame("https://x.example/", name="aswift_2")
    assert not _is_ad_frame("https://boards.greenhouse.io/embed/job_app?for=acme")


def test_prefer_known_click_beats_phrase_rank_but_not_deny():
    B = lambda n: {"name": n, "role": "button"}
    # learned route says step 1 is "Continue to role"; no phrase ranks that highly
    cands = [B("Apply now"), B("Continue to role")]
    assert _best_apply(cands, prefer=["Continue to role"])["name"] == "Continue to role"
    assert _best_apply(cands)["name"] == "Apply now"                       # no hint -> unchanged
    # earlier step in the learned route wins over a later one
    assert _best_apply([B("I'm ready to apply"), B("Apply now")],
                       prefer=["Apply now", "I'm ready to apply"])["name"] == "Apply now"
    # a denied name is never rescued by the hint
    assert _best_apply([B("Share job")], prefer=["Share job"]) is None


def test_login_wall_definition():
    # the SuccessFactors login page seen live: email + password, Sign In / Forgot password / Create an account
    assert login_from_signals({"hasPassword": True, "hasUser": True, "authControl": True, "credInputs": 2})
    assert login_from_signals({"hasPassword": True, "hasUser": False, "authControl": True, "credInputs": 1})   # control tells it
    assert login_from_signals({"hasPassword": True, "hasUser": True, "authControl": False, "credInputs": 4})   # sign-up form
    # NOT a wall: no password box; or a password box inside a long application form (combined registration+application)
    assert not login_from_signals({"hasPassword": False, "hasUser": True, "authControl": True, "credInputs": 1})
    assert not login_from_signals({"hasPassword": True, "hasUser": True, "authControl": True, "credInputs": 12})
    assert not login_from_signals({})


def test_saved_logins_are_filed_per_tenant_not_just_per_host():
    # SuccessFactors: one host, one account per company -> a login saved for another company must not match
    sf = "https://career44.sapsf.com/careers?company=BirlasoftL"
    assert site_key(sf) == "career44.sapsf.com?company=birlasoftl"
    assert site_key("https://career44.sapsf.com/careers?company=otherco") != site_key(sf)
    # the old host-only key is NOT what a tenant URL maps to any more (so the sign-up path runs for a new tenant)
    assert site_key(sf) != "career44.sapsf.com"
    # hosts with no tenant in the URL keep their plain host key (existing saved logins stay valid)
    assert site_key("https://himalayas.app/onboarding/talent") == "himalayas.app"
    assert site_key("https://walmart.wd504.myworkdayjobs.com/en-US/x/login") == "walmart.wd504.myworkdayjobs.com"
    assert site_key("") == "" and site_key("not a url") == ""


def test_new_tab_since_adopts_only_a_tab_that_really_opened():
    from career_agent.browser.page_prep import new_tab_since

    class P:
        def __init__(self, ctx, closed=False): self.context, self._c = ctx, closed
        def is_closed(self): return self._c

    class Ctx: pages = []
    ctx = Ctx(); mine, other_job = P(ctx), P(ctx); ctx.pages = [mine, other_job]
    before = list(ctx.pages)
    assert new_tab_since(mine, before) is mine                      # nothing opened: stay on this job's tab, not the last one
    popup = P(ctx); ctx.pages = [mine, other_job, popup]
    assert new_tab_since(mine, before) is popup                     # a genuinely new tab is adopted
    popup._c = True
    assert new_tab_since(mine, before) is mine                      # unless it already closed


def test_footer_social_links_are_never_an_apply_control():
    from career_agent.browser.page_prep import _best_apply
    cands = [{"name": "Siemens Facebook external link (opens in a new tab)", "role": "link", "ref": "a"},
             {"name": "Apply now", "role": "button", "ref": "b"}]
    assert _best_apply(cands)["ref"] == "b"
    assert _best_apply(cands[:1]) is None


def test_advance_click_that_starts_a_slow_navigation_is_not_repeated(monkeypatch):
    import os, threading, time, http.server, socketserver
    from career_agent.browser import clicks
    monkeypatch.setattr(clicks, "TIMING_SCALE", 0.01)
    if os.getenv("RUN_BROWSER_TESTS") != "1":
        import pytest; pytest.skip("browser")
    from playwright.sync_api import sync_playwright
    from career_agent.orchestrator.browser_deps import BrowserDeps

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/step2":
                time.sleep(2)                                    # slower than the click's own timeout
            body = {"/": b"<a href=/step2>Continue</a>", "/step2": b"<a href=/step3>Continue</a>"}.get(self.path, b"done")
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(); pg.goto(f"http://127.0.0.1:{port}/")
        BrowserDeps.click(object.__new__(BrowserDeps), pg, "Continue")
        assert pg.url.endswith("/step2"), pg.url                  # one click: step 2, never skipped on to step 3
        b.close()
    srv.shutdown()


def test_dismiss_dialogs_never_clicks_the_pages_own_continue():
    import os
    if os.getenv("RUN_BROWSER_TESTS") != "1":
        import pytest; pytest.skip("browser")
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import dismiss_dialogs

    page_continue = "<button id=go onclick=\"document.title='advanced'\">Continue</button>"
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page()
        pg.set_content("<div role=dialog style='display:none'><button>Close</button></div>" + page_continue)
        assert dismiss_dialogs(pg) is False and pg.title() != "advanced"        # hidden dialog: nothing to dismiss
        pg.set_content("<div role=dialog><p>Session idle</p><button id=k onclick=\"this.parentElement.remove()\">Continue Working</button></div>" + page_continue)
        assert dismiss_dialogs(pg) is True and pg.title() != "advanced"         # the modal's own button, not the page's
        assert pg.locator("[role=dialog]").count() == 0
        pg.set_content("<div role=dialog><p>Notice</p><button onclick=\"this.parentElement.remove()\">Dismiss</button></div>" + page_continue)
        assert dismiss_dialogs(pg) is True and pg.title() != "advanced"
        b.close()
