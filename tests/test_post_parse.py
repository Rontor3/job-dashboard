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


def test_garbage_html_returns_empty_never_raises():
    assert parse_posts_html("") == []
    assert parse_posts_html("<html><body>nothing</body></html>") == []
    assert parse_posts_html("<div data-view-name='feed-full-update'></div>") == []
