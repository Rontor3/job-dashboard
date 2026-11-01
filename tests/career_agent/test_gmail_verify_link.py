"""Workday's 'Verify your candidate account' (Capital One, 2026-11-01): HTML only, two levels deep."""
import base64

from career_agent.integrations import gmail_otp as g

HTML = ('<html><style>td{width:6000px;color:#123456}</style><body><p>Welcome</p>'
        '<a href="https://capitalone.wd12.myworkdayjobs.com/Capital_One/activate/abcDEF123456/?redirect=%2Fjob&amp;x=1">'
        'Verify</a></body></html>')


class _Svc:
    def users(self): return self
    def messages(self): return self
    def get(self, **kw): return self
    def execute(self):
        enc = base64.urlsafe_b64encode(HTML.encode()).decode()
        return {"payload": {"mimeType": "multipart/mixed", "parts": [
            {"mimeType": "multipart/related", "parts": [{"mimeType": "text/html", "body": {"data": enc}}]}]},
            "snippet": "Verify your candidate account https://capitalone.wd12"}


def test_nested_html_body_keeps_the_whole_link_and_drops_style_numbers():
    body = g._body_text(_Svc(), "m1")
    links = g._VERIFY_LINK_RE.findall(body)
    assert links and links[0].startswith("https://capitalone.wd12.myworkdayjobs.com/Capital_One/activate/abcDEF123456")
    assert "&x=1" in links[0] and "6000" not in body


def test_only_a_link_on_the_signup_site_counts():
    site = "capitalone.wd12.myworkdayjobs.com"
    assert g._same_site("https://capitalone.wd12.myworkdayjobs.com/x/activate/1", site)
    assert not g._same_site("https://evil.example.com/verify?x", site)
