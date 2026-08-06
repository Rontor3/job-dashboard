import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("LINKEDIN_LI_AT"), reason="no LinkedIn cookie in env"
)


def test_live_search_returns_list():
    from job_dashboard.linkedin.browser_fetch import LinkedInBrowserFetcher
    f = LinkedInBrowserFetcher(os.environ["LINKEDIN_LI_AT"],
                               os.environ["LINKEDIN_JSESSIONID"], headless=True)
    posts = f.search_posts("hiring ML engineer")
    assert isinstance(posts, list)   # >=0; content varies day to day
