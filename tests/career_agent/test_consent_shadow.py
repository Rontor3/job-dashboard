"""A cookie banner drawn inside a shadow root (Usercentrics) is found and declined — it covered FedEx's Apply."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

PAGE = """<html><body><h1>Data Scientist</h1><a href="#" id="apply" onclick="document.title='applied';return false">Apply</a>
<div id="usercentrics-root"></div>
<script>
  const r = document.getElementById('usercentrics-root').attachShadow({mode: 'open'});
  r.innerHTML = '<div style="position:fixed;inset:0;background:#fff;z-index:9"><p>FedEx is using cookies</p>'
    + '<button id=rej onclick="this.getRootNode().host.remove();document.title=\\'rejected\\'">REJECT OPTIONAL COOKIES</button>'
    + '<button>ACCEPT ALL COOKIES</button></div>';
</script></body></html>"""


def test_a_shadow_root_cookie_banner_is_declined_and_apply_can_be_clicked():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import dismiss_consent
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(); pg.set_content(PAGE)
        assert dismiss_consent(pg) is True
        assert pg.title() == "rejected"                      # the privacy-preserving choice, not Accept all
        pg.click("#apply", timeout=3000)
        assert pg.title() == "applied"
        b.close()
