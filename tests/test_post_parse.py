from job_dashboard.linkedin.post_parse import parse_posts_html

# Minimal shape mirroring a rendered content-search result card.
FIXTURE = """
<div data-view-name="feed-full-update" data-urn="urn:li:activity:12345">
  <a class="update-components-actor__meta-link" href="https://www.linkedin.com/in/jane">
    <span class="update-components-actor__title"><span>Jane Doe</span></span>
    <span class="update-components-actor__description">Engineering Manager @ Acme</span>
    <span class="update-components-actor__sub-description">5h • Edited</span>
  </a>
  <div class="update-components-text">We're hiring an ML Engineer! DM me.</div>
</div>
<div data-view-name="feed-full-update" data-urn="urn:li:activity:67890">
  <div class="update-components-text">No actor/url here — should be skipped</div>
</div>
"""


def test_parses_one_valid_card():
    posts = parse_posts_html(FIXTURE)
    assert len(posts) == 1                      # second card missing url/name skipped
    p = posts[0]
    assert p["poster_name"] == "Jane Doe"
    assert "ML Engineer" in p["text"]
    assert p["url"].endswith("/activity:12345") or "12345" in p["url"]
    assert "Acme" in p["poster_headline"]
    assert "5h" in (p["posted_at"] or "")


def test_relative_fallback_url_is_made_absolute():
    # A card with no data-urn but a relative permalink href must yield an
    # absolute URL so the "View on LinkedIn" link isn't broken.
    html = """
    <div data-view-name="feed-full-update">
      <span class="update-components-actor__title"><span>Sam Roe</span></span>
      <a href="/feed/update/urn:li:activity:999/">permalink</a>
      <div class="update-components-text">Hiring a data scientist</div>
    </div>"""
    posts = parse_posts_html(html)
    assert len(posts) == 1
    assert posts[0]["url"].startswith("https://www.linkedin.com/feed/update/")


def test_garbage_html_returns_empty_never_raises():
    assert parse_posts_html("") == []
    assert parse_posts_html("<html><body>nothing</body></html>") == []
    assert parse_posts_html("<div data-view-name='feed-full-update'></div>") == []
