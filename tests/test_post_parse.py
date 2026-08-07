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
  <a href="https://www.linkedin.com/jobs/view/4416153365/?trackingId=abc%3D%3D">View job</a>
</div>
<div role="listitem" class="_51373152">
  <a href="https://www.linkedin.com/in/sam-roe/"><img alt="View Sam Roe’s profile, hiring"></a>
  <p>Feed post Sam Roe • 2nd Talent Lead 13h • Follow
     #hiringalert We're looking for a Data Scientist (2+ yrs).</p>
  <a href="https://www.linkedin.com/safety/go/?url=https%3A%2F%2Flnkd%2Ein%2FgAK9wphM&urlhash=x">apply</a>
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
    # url is the actual JOB posting, tracking params stripped
    assert jane["url"] == "https://www.linkedin.com/jobs/view/4416153365/"


def test_hiring_badge_name_is_clean():
    # "View Sam Roe’s profile, hiring" → just "Sam Roe"
    posts = parse_posts_html(FIXTURE)
    assert posts[1]["poster_name"] == "Sam Roe"
    assert "profile" not in posts[1]["poster_name"].lower()


def test_external_apply_link_decoded_from_safety_redirect():
    # LinkedIn wraps external links in /safety/go/?url=<encoded>; we unwrap it.
    posts = parse_posts_html(FIXTURE)
    assert posts[1]["url"] == "https://lnkd.in/gAK9wphM"


def test_profile_fallback_when_no_job_link():
    # No job/apply link → link to the poster's profile, uniquified by body hash.
    html = """
    <div role="listitem">
      <a href="https://www.linkedin.com/in/nolink/"><img alt="View No Link’s profile"></a>
      <p>Feed post No Link • 3rd Recruiter 2h • Connect We are hiring a data scientist, DM me.</p>
    </div>"""
    p = parse_posts_html(html)[0]
    assert p["url"].startswith("https://www.linkedin.com/in/nolink/#")


def test_garbage_html_returns_empty_never_raises():
    assert parse_posts_html("") == []
    assert parse_posts_html("<html><body>nothing</body></html>") == []
    assert parse_posts_html("<div role='listitem'></div>") == []
