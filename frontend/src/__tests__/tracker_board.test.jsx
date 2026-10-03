import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, test, vi, beforeEach } from "vitest";
import TrackerBoard from "../components/TrackerBoard.jsx";

const BOARD = {
  saved: [{ id: 1, title: "DS", company: "Acme", industry: "BFSI", status: "saved" }],
  applied: [{ id: 2, title: "MLE", company: "Globex", status: "applied" }],
  interviewing: [], offer: [],
  archived: [{ id: 3, title: "AI", company: "Soylent", status: "rejected" }],
};

const OPEN_Q = { id: 7, label: "Why do you want to work here?", source: "judgment", confidence: 30,
  basis: "guessed", answer: "Draft answer", unsupported_claims: ["Series B"], context_json: { prompt: "PROMPT TEXT" } };

function mockFetch({ agentStatus = { running: false, job_id: null }, questions = [OPEN_Q], counts = { 1: 1 } } = {}) {
  const state = { questions: [...questions], counts: { ...counts } };
  const fn = vi.fn((url, opts) => {
    const u = String(url);
    if (u.includes("/questions/7/reply")) {
      state.questions = []; state.counts = {};
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    }
    if (u.includes("/api/questions/open-counts"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(state.counts) });
    if (u.includes("/api/jobs/1/questions"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ questions: state.questions }) });
    if (u.includes("/agent-runs/log"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ job_id: 1, lines: ["[step] snapshot...", "[fill] step 1: 4 filled"] }) });
    if (u.includes("/api/apply-agent/status"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(agentStatus) });
    if (u.includes("/mail-scan/status"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ running: false, last_scan: 0, connected: true, last_result: null }) });
    if (u.includes("/api/tracker"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(BOARD) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
  });
  return fn;
}

beforeEach(() => {
  global.fetch = mockFetch();
});

function lastPatch() {
  const calls = global.fetch.mock.calls.filter(([, o]) => o && o.method === "PATCH");
  const [url, opts] = calls[calls.length - 1];
  return { url: String(url), body: JSON.parse(opts.body) };
}

test("renders rows (not columns) with a status pill, plus archived", async () => {
  render(<TrackerBoard onSelect={() => {}} />);
  expect(await screen.findByText("DS")).toBeInTheDocument();
  expect(screen.getByText("MLE")).toBeInTheDocument();
  expect(screen.getByTestId("status-pill-1")).toHaveTextContent("Queued");
  expect(screen.getByTestId("status-pill-2")).toHaveTextContent("Applied");
  expect(screen.queryByTestId("col-interviewing")).toBeNull(); // no column layout anymore
  expect(screen.getByText("AI")).toBeInTheDocument(); // inside the archived <details>
});

test("changing the stage select patches to that stage, with the interview round", async () => {
  const onStatsChange = vi.fn();
  render(<TrackerBoard onSelect={() => {}} onStatsChange={onStatsChange} />);
  await screen.findByText("DS");
  fireEvent.change(screen.getByTestId("stage-1"), { target: { value: "interviewing:2" } });
  await waitFor(() => {
    const p = lastPatch();
    expect(p.url).toContain("/api/jobs/1/status");
    expect(p.body).toEqual({ status: "interviewing", round: 2 });
  });
  await waitFor(() => expect(onStatsChange).toHaveBeenCalled());
  fireEvent.change(screen.getByTestId("stage-1"), { target: { value: "failed" } });
  await waitFor(() => expect(lastPatch().body).toEqual({ status: "failed" }));
});

test("failed rows say why, interviewing rows say the round", async () => {
  const board = { ...BOARD,
    failed: [{ id: 4, title: "SWE", company: "Baz", status: "failed", queue_state: "parked", queue_reason: "needs_answers" }],
    interviewing: [{ id: 5, title: "PM", company: "Qux", status: "interviewing", interview_round: 2 }] };
  const base = mockFetch();
  global.fetch = vi.fn((url, opts) => String(url).includes("/api/tracker")
    ? Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(board) }) : base(url, opts));
  render(<TrackerBoard onSelect={() => {}} />);
  expect(await screen.findByTestId("status-pill-4")).toHaveTextContent("Failed — questions to answer");
  expect(screen.getByTestId("status-pill-5")).toHaveTextContent("Round 2");
  expect(screen.getByTestId("stage-5").value).toBe("interviewing:2");
});

test("select Remove untracks via status null", async () => {
  render(<TrackerBoard onSelect={() => {}} />);
  await screen.findByText("DS");
  fireEvent.change(screen.getByTestId("stage-1"), { target: { value: "__remove__" } });
  await waitFor(() => {
    const p = lastPatch();
    expect(p.url).toContain("/api/jobs/1/status");
    expect(p.body.status).toBe(null);
  });
});

test("a row for the currently-running job shows a live Filling tag instead of its stage pill", async () => {
  global.fetch = mockFetch({ agentStatus: { running: true, job_id: 1, title: "Application form" } });
  render(<TrackerBoard onSelect={() => {}} />);
  await screen.findByText("DS");
  await waitFor(() =>
    expect(screen.getByTestId("status-pill-1")).toHaveTextContent("Filling — Application form"));
  // job 2 isn't the running one -> still shows its normal stage pill
  expect(screen.getByTestId("status-pill-2")).toHaveTextContent("Applied");
});

test("clicking a row expands it inline (no drawer); Details opens the drawer; stage select doesn't toggle", async () => {
  const onSelect = vi.fn();
  render(<TrackerBoard onSelect={onSelect} />);
  await screen.findByText("DS");
  fireEvent.click(screen.getByTestId("stage-1"));
  expect(screen.queryByTestId("expand-1")).toBeNull();
  fireEvent.click(screen.getByText("DS"));
  expect(await screen.findByTestId("expand-1")).toBeInTheDocument();
  expect(onSelect).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(onSelect).toHaveBeenCalledWith(1);
  fireEvent.click(screen.getByText("DS"));
  expect(screen.queryByTestId("expand-1")).toBeNull();
});

test("row shows an open-questions badge; expanded panel shows draft confidence, basis, context", async () => {
  render(<TrackerBoard onSelect={() => {}} />);
  expect(await screen.findByTestId("open-badge-1")).toHaveTextContent("1 to answer");
  expect(screen.queryByTestId("open-badge-2")).toBeNull();
  fireEvent.click(screen.getByText("DS"));
  expect(await screen.findByText("Why do you want to work here?")).toBeInTheDocument();
  expect(screen.getByText(/30\/100 — guessed/)).toBeInTheDocument();
  expect(screen.getByText(/not found in context: Series B/)).toBeInTheDocument();
  expect(screen.getByText("PROMPT TEXT")).toBeInTheDocument();
});

test("replying posts the answer, and the question leaves the tracker", async () => {
  render(<TrackerBoard onSelect={() => {}} />);
  await screen.findByText("DS");
  fireEvent.click(screen.getByText("DS"));
  const box = await screen.findByLabelText(/Answer for Why do you want/);
  expect(box.value).toBe("Draft answer");                  // draft prefilled to edit
  fireEvent.change(box, { target: { value: "Because fraud ML." } });
  fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
  await waitFor(() => {
    const post = global.fetch.mock.calls.find(([u]) => String(u).includes("/questions/7/reply"));
    expect(JSON.parse(post[1].body)).toEqual({ answer: "Because fraud ML.", save_as: "once", entry_id: null });
  });
  expect(await screen.findByText("No open questions.")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByTestId("open-badge-1")).toBeNull());
});

test("running row shows live screenshot and streaming log; other rows don't", async () => {
  global.fetch = mockFetch({ agentStatus: { running: true, job_id: 1, title: "Form", screenshot: "/api/jobs/1/agent-runs/live-screenshot" } });
  render(<TrackerBoard onSelect={() => {}} />);
  expect(await screen.findByTestId("live-view-1")).toBeInTheDocument();
  expect(await screen.findByText(/\[fill\] step 1: 4 filled/)).toBeInTheDocument();
  expect(screen.getByAltText(/Live view/)).toBeInTheDocument();
  expect(screen.queryByTestId("live-view-2")).toBeNull();
});

test("a general question defaults to Add to Answers; a why-this-company essay stays with the application", async () => {
  const general = { id: 8, label: "Expected CTC in LPA?", source: "human", answer: "" };
  global.fetch = mockFetch({ questions: [general, OPEN_Q] });
  render(<TrackerBoard onSelect={() => {}} />);
  fireEvent.click(await screen.findByText("DS"));
  await screen.findByText("Expected CTC in LPA?");
  const radios = (id) => screen.getByTestId("questions-1").querySelectorAll(`input[name="mode-${id}"]`);
  expect([...radios(8)].find((r) => r.checked).parentElement.textContent).toContain("Add to Answers");
  expect([...radios(7)].find((r) => r.checked).parentElement.textContent).toContain("Just this application");
});
