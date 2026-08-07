# LinkedIn Hiring Digest — Runbook

## Prerequisites

- **Google Chrome** (required for Selenium WebDriver; Safari/Firefox not supported for this session's cookie auth)
- **Python packages**: `pip3 install selenium beautifulsoup4` (see `requirements.txt`)
- **.env file** with LinkedIn session cookies

## Step 1: Extract LinkedIn Cookies

1. Open LinkedIn in Chrome
2. Press **F12** to open DevTools
3. Navigate to **Application → Cookies → linkedin.com**
4. Copy the value of the cookie named **`li_at`**
5. Copy the value of the cookie named **`JSESSIONID`**

## Step 2: Set Environment Variables

Add the following to `.env` in the project root:

```bash
LINKEDIN_LI_AT=<paste-li_at-value-here>
LINKEDIN_JSESSIONID=<paste-jsessionid-value-here>
```

These cookies authenticate the browser without login automation. They expire roughly once per month.

## Step 3: How It Works

When you click **Refresh** on the Hiring Signals tab:

1. A real Chrome window opens. The Refresh flow runs **headful** (a visible
   window) so it looks like a normal browser and clears LinkedIn's bot check —
   raw HTTP does not work, which is why we drive a real browser. (Only the
   automated `tests/test_hiring_live.py` runs headless.)
2. The browser loads `linkedin.com`, injects your `li_at`/`JSESSIONID` cookies,
   and reloads so it is logged in as you (no password, no login automation).
3. For each keyword (e.g., "hiring ML engineer"), the browser:
   - Navigates the **content-search** page with the **past-24h** filter
   - Scrolls a few times with randomized human-paced delays to load posts
   - Scrapes the rendered post HTML with BeautifulSoup — poster name,
     headline, hiring text, posted timestamp, and the **job/apply link** found
     in the post (the LinkedIn `jobs/view` posting, or an external `lnkd.in`
     apply link; falls back to the poster's profile when a post has no link)
4. Posts are deduplicated by URL, ranked against your profile, and stored with a
   24-hour window
5. The browser window closes

The default driver is **undetected-chromedriver** (installed via requirements),
which hides the automation fingerprints LinkedIn's bot detection checks for; it
falls back to plain Selenium if unavailable.

### If Refresh returns 0 posts

Auth/stealth/navigation can all be working and LinkedIn can still return an
**empty page** when the session is temporarily **soft-flagged** — usually after
a burst of automated requests in a short window. This clears on its own; wait a
few hours (ideally browse LinkedIn normally in the meantime) and hit Refresh
again. Running the digest sparingly (a few times a day, not in a tight loop) is
what keeps the session healthy.

Total time: ~2–3 minutes for a full refresh across all keywords.

## Step 4: Constraints & ToS

**Read-only & low-volume**: This fetcher only reads data — no logins, posts, or uploads.

**LinkedIn Terms of Service**: LinkedIn discourages scraping. Use responsibly:
- ✓ Daily manual refresh (human-paced)
- ✓ Hiring role with legitimate business use
- ✗ Automated 24/7 crawls
- ✗ Unattended execution
- ✗ Scaling to thousands of keywords

**Over-use & session soft-flagging**: If LinkedIn detects excessive volume, it may:
- Temporarily soft-flag your session (blocks search)
- Clear cookies after ~30 days (normal expiry)

There is no hard block — the session clears itself. Simply re-paste cookies.

## Step 5: Session Expiry

Cookies last ~30 days. When they expire:

- The Hiring Signals tab displays: **"Session expired — re-paste cookies"**
- Extract new `li_at` and `JSESSIONID` from DevTools (Step 1)
- Update `.env` and restart the server

## Step 6: Usage

1. Open the **Hiring Signals** tab in the Job Dashboard
2. Click the **Refresh** button (bottom right)
3. Wait 2–3 minutes for the browser window to finish searching and close
4. Refreshed posts appear in the feed

Do not run multiple refreshes in parallel — wait for one to complete.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "No Chrome found" | Ensure Google Chrome (not Chromium or Edge) is installed at `/Applications/Google Chrome.app` |
| "Session expired" | Extract fresh cookies and update `.env` |
| "Test skipped" | Set `LINKEDIN_LI_AT` and `LINKEDIN_JSESSIONID` env vars to run the live e2e test |
