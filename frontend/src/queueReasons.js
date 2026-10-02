// Why the apply queue parked or failed a job, in words (shared by the queue
// panel and the tracker). Keys are apply_queue.reason values.
export const QUEUE_REASON = {
  needs_answers: "questions to answer", review: "filled — review & submit", needs_approval: "best-guess answers",
  one_click_needs_autosubmit: "one-click board: turn on auto-submit", logged_out: "log in to the board",
  challenge: "bot check", daily_cap: "daily cap reached", closed: "posting closed", crashed: "agent crashed",
  no_result: "agent crashed", launch_error: "couldn't start the agent", job_missing: "job missing",
  unconfirmed: "submitted, not confirmed", stuck: "stuck on a page", no_entry: "no apply button",
  auth_wall: "login wall", error: "agent error",
};

export const reasonText = (reason) => (reason ? QUEUE_REASON[reason] || reason.replace(/_/g, " ") : "");
