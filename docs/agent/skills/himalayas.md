---
description: Himalayas.app jobs: the posting usually sends you to the company's own careers site
---
# Himalayas

- **The posting page:** a Himalayas job page has "Apply now", often followed by a dialog with "I'm ready to apply"
  that opens the company's own site (Zoho Recruit, Lever, Greenhouse, Workable...). `apply_reach` follows that path,
  and the rest is a career-site form.
- **Location:** many Himalayas jobs are open only to people in the US, UK or Canada. If the posting says so and the
  user's location is elsewhere, skip it with reason `not_eligible`.
- **Walls:** company sites behind Himalayas often have a captcha (Zoho does). The run is skipped there. Never try to
  get past one.
- **Sign-in:** a Himalayas sign-in or "verify your email" page means the user must log in once in the agent's
  Chrome, so skip with `account_needed`.
