import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import AgentRunHistory from "../components/AgentRunHistory.jsx";

const Q = (over) => ({ id: 1, label: "Q?", kind: "text", answer: "A", source: "qbank", status: "filled", origin: "saved",
                       matched: null, match_kind: null, score: null, confidence: null, basis: null,
                       unsupported_claims: [], prompt: null, outcome: null, ...over });
const STEP = (step, questions, over = {}) => ({ step, kind: "form", cred_action: null, stopped_reason: null,
                                                 pending_human: [], gate_notice: null, screenshot: null, questions, ...over });

function mock(run) {
  const state = { run };
  global.fetch = vi.fn((url, opts) => {
    const u = String(url);
    const ok = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body), text: () => Promise.resolve("") });
    if (u.includes("/review")) {
      const b = JSON.parse(opts.body);
      const id = Number(u.match(/application-qa\/(\d+)\/review/)[1]);
      state.run = { ...state.run, steps: state.run.steps.map((s) => ({ ...s, questions: s.questions.map((q) =>
        (q.id === id ? { ...q, outcome: b.verdict === "wrong" ? "edited" : "kept" } : q)) })) };
      return ok({ ok: true });
    }
    if (u.includes("/api/qbank/entries"))
      return ok({ entries: [{ id: "skill_years", question: "How many years of experience do you have with this skill?", topic: "experience" }] });
    if (u.includes("/agent-runs/latest")) return ok(state.run);
    return ok({});
  });
}

const RUN = {
  job_id: 1, unpaged: [],
  steps: [
    STEP(0, [Q({ id: 1, label: "Notice period?", answer: "30 days", origin: "saved_exact", match_kind: "exact", matched: "notice period?" }),
             Q({ id: 2, label: "Years of Python?", answer: "2", origin: "similar", source: "qbank_likely", matched: "years of java", score: 0.6 }),
             Q({ id: 3, label: "Current city?", answer: "Pune", origin: "profile", source: "standard" })]),
    STEP(1, [Q({ id: 4, label: "Why do you want to join Acme?", answer: "Line one.\nLine two.", origin: "model", source: "judgment",
                confidence: 72, basis: "from the JD", unsupported_claims: ["Series B"], prompt: "THE PROMPT" }),
             Q({ id: 5, label: "Expected CTC?", answer: null, origin: "open", status: "needs_answer" })],
         { kind: "stop", stopped_reason: "needs_human" }),
  ],
};

test("each page is its own block with its questions, answers and where each came from", async () => {
  mock(RUN);
  render(<AgentRunHistory jobId={1} />);
  const p0 = within(await screen.findByTestId("page-0"));
  expect(p0.getByText("Notice period?")).toBeInTheDocument();
  expect(p0.getByText("30 days")).toBeInTheDocument();
  expect(p0.getByText(/matched “notice period\?” · exact wording/)).toBeInTheDocument();
  expect(p0.getAllByText("From your Answers")).toHaveLength(1);
  expect(p0.getByText("Best guess from a similar answer")).toBeInTheDocument();
  expect(p0.getByText(/matched “years of java” · match 0.6 · check it/)).toBeInTheDocument();
  expect(p0.getByText("From your profile")).toBeInTheDocument();
  const p1 = within(screen.getByTestId("page-1"));
  expect(p1.getByText("Why do you want to join Acme?")).toBeInTheDocument();
  expect(p1.queryByText("Notice period?")).toBeNull();                       // belongs to page 1, not here
});

test("a model draft shows confidence, basis, unsupported claims, the prompt and keeps its line breaks", async () => {
  mock(RUN);
  render(<AgentRunHistory jobId={1} />);
  const p1 = within(await screen.findByTestId("page-1"));
  expect(p1.getByText("Written by the model")).toBeInTheDocument();
  expect(p1.getByText(/confidence 72\/100 — from the JD · not found in context: Series B/)).toBeInTheDocument();
  expect(p1.getByText(/Line one\./).style.whiteSpace).toBe("pre-wrap");
  expect(p1.getByText("THE PROMPT")).toBeInTheDocument();
  expect(p1.getByText("Needs your answer")).toBeInTheDocument();
  expect(p1.queryByRole("button", { name: /Correct:/ })).toBeNull();        // only saved/similar answers are reviewable
});

test("marking a saved answer correct posts and shows the verdict", async () => {
  mock(RUN);
  render(<AgentRunHistory jobId={1} />);
  fireEvent.click(await screen.findByRole("button", { name: /Correct: Years of Python/ }));
  expect(await screen.findByText("marked correct")).toBeInTheDocument();
  const post = global.fetch.mock.calls.find(([u]) => String(u).includes("/application-qa/2/review"));
  expect(JSON.parse(post[1].body)).toMatchObject({ verdict: "correct" });
});

test("marking wrong points the answer at the right saved question; Save fix needs a pick first", async () => {
  mock(RUN);
  render(<AgentRunHistory jobId={1} />);
  fireEvent.click(await screen.findByRole("button", { name: /Wrong: Years of Python/ }));
  expect(screen.getByRole("button", { name: "Save fix" })).toBeDisabled();
  const picker = screen.getByLabelText(/Right question for Years of Python/);
  await waitFor(() => expect(global.fetch.mock.calls.some(([u]) => String(u).includes("/api/qbank/entries"))).toBe(true));
  fireEvent.change(picker, { target: { value: "How many years of experience do you have with this skill?" } });
  fireEvent.click(screen.getByRole("button", { name: "Save fix" }));
  await waitFor(() => {
    const post = global.fetch.mock.calls.find(([u]) => String(u).includes("/application-qa/2/review"));
    expect(JSON.parse(post[1].body)).toEqual({ verdict: "wrong", entry_id: "skill_years" });
  });
  expect(await screen.findByText("marked wrong")).toBeInTheDocument();
});

test("questions from older runs with no page are listed after the pages", async () => {
  mock({ ...RUN, unpaged: [Q({ id: 9, label: "Legacy question?", answer: "x", origin: "you", source: "human" })] });
  render(<AgentRunHistory jobId={1} />);
  expect(await screen.findByText("Other questions in this run")).toBeInTheDocument();
  expect(screen.getByText("Legacy question?")).toBeInTheDocument();
  expect(screen.getByText("Your answer")).toBeInTheDocument();
});

test("board runs: the stop page says why, and a plain-string pending list still reads", async () => {
  mock({ job_id: 1, unpaged: [], steps: [STEP(0, [], { kind: "stop", stopped_reason: "needs_human", pending_human: ["Expected CTC"] })] });
  render(<AgentRunHistory jobId={1} />);
  expect(await screen.findByText(/Where it stopped/)).toBeInTheDocument();
  expect(screen.getByText(/Stopped for questions you need to answer/)).toBeInTheDocument();
  expect(screen.getByText(/Stuck on: Expected CTC/)).toBeInTheDocument();
});
