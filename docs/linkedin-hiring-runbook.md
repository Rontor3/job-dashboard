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

1. A real Chrome browser window opens (not headless)
2. The browser sends a `GET` request to LinkedIn's `linkedin.com/voyager` endpoint with your cookies
3. For each keyword (e.g., "hiring ML engineer"), the browser:
   - Searches LinkedIn's hiring signals API
   - Scrapes post HTML using BeautifulSoup
   - Extracts: URL, poster name, headline, text, posted timestamp
4. Posts are deduplicated by URL and stored in the database with a 24-hour window
5. The browser window closes

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
