// Why the apply queue parked or failed a job, in words (shared by the queue
// panel and the tracker). Keys are apply_queue.reason values.
export const QUEUE_REASON = {
  needs_answers: "questions to answer", review: "filled — review & submit", needs_approval: "best-guess answers",
  one_click_needs_autosubmit: "one-click board: turn on auto-submit", logged_out: "log in to the board",
  challenge: "bot check", daily_cap: "daily cap reached", closed: "posting closed", crashed: "agent crashed",
  no_result: "agent crashed", launch_error: "couldn't start the agent", job_missing: "job missing",
  unconfirmed: "submitted, not confirmed", stuck: "stuck on a page", no_entry: "no apply button",
  auth_wall: "login wall", error: "agent error",
  sensitive_field: "needs bank/ID details — fill them yourself",
};

export const reasonText = (reason) => (reason ? QUEUE_REASON[reason] || reason.replace(/_/g, " ") : "");

// What to do about each stop, in one plain sentence (shown under a failed tracker row).
const RETRY = "Re-queue to try again. If it stops the same way, expand the row to see the run.";
export const QUEUE_FIX = {
  error: RETRY, crashed: RETRY, no_result: RETRY,
  launch_error: "Re-queue to try again. If it keeps failing, check that Google Chrome is installed.",
  logged_out: "Log in to this site in the agent's Chrome window, then Re-queue.",
  auth_wall: "Log in to this site in the agent's Chrome window, then Re-queue.",
  challenge: "Solve the bot check in the agent's Chrome window, then Re-queue.",
  stuck: "Expand the row to see the page it got stuck on. Finish it by hand there, or Re-queue.",
  no_entry: "The agent couldn't find an apply button. Open the posting and apply by hand.",
  closed: "The posting is closed. Remove it from the board.",
  job_missing: "The job no longer exists. Remove it from the board.",
  daily_cap: "This site's daily limit is reached. Re-queue tomorrow.",
  sensitive_field: "Fill the bank/ID fields yourself in the agent's Chrome window, then submit there.",
  unconfirmed: "Check your email for a confirmation. If it arrived, mark this Applied.",
  one_click_needs_autosubmit: "Turn on auto-submit for this board (queue → Manage), then Re-queue.",
};
export const fixText = (reason) => QUEUE_FIX[reason] || RETRY;
