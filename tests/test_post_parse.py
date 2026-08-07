from job_dashboard.linkedin.post_parse import parse_posts_html

# Mirrors LinkedIn's real server-driven search-result DOM: a role="listitem"
# card with hashed classes, the poster name only in the avatar img alt
# ("View {Name}'s profile[, hiring]"), a /in/ profile link, and the actor line
# ending with a connection-degree/Connect control before the post body.
FIXTURE = """
<div role="listitem" class="_51373152 _914b0cc2">
  <a href="https://www.linkedin.com/in/jane-doe-123/?misc=1"><img alt="View Jane Doe’s profile"></a>
  <p>Feed post Jane Doe • 3rd+ Engineering Manager at Acme 4h • Connect
     🚀 We're hiring an ML Engineer! DM me if interested.</p>
</div>
<div role="listitem" class="_51373152">
  <a href="https://www.linkedin.com/in/sam-roe/"><img alt="View Sam Roe’s profile, hiring"></a>
  <p>Feed post Sam Roe • 2nd Talent Lead 13h • Follow
     #hiringalert We're looking for a Data Scientist (2+ yrs).</p>
</div>
<div role="listitem">
  <p>a card with no poster/profile — should be skipped</p>
</div>
"""


def test_parses_listitem_cards():
    posts = parse_posts_html(FIXTURE)
    assert len(posts) == 2                       # third card (no profile) skipped
    jane = posts[0]
    assert jane["poster_name"] == "Jane Doe"     # "'s profile" stripped
    assert "ML Engineer" in jane["text"]
    assert "Connect" not in jane["text"]         # actor line removed from body
    assert jane["posted_at"] == "4h"
    assert "Engineering Manager" in jane["poster_headline"]
    assert jane["url"].startswith("https://www.linkedin.com/in/jane-doe-123/#")


def test_hiring_badge_name_is_clean():
    # "View Sam Roe’s profile, hiring" → just "Sam Roe"
    posts = parse_posts_html(FIXTURE)
    assert posts[1]["poster_name"] == "Sam Roe"
    assert "profile" not in posts[1]["poster_name"].lower()


def test_same_person_two_posts_not_deduped():
    # Body hash in the URL fragment keeps distinct posts by one person distinct.
    posts = parse_posts_html(FIXTURE)
    assert posts[0]["url"] != posts[1]["url"]


def test_garbage_html_returns_empty_never_raises():
    assert parse_posts_html("") == []
    assert parse_posts_html("<html><body>nothing</body></html>") == []
    assert parse_posts_html("<div role='listitem'></div>") == []
