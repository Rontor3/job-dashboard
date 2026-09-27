import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import AnswersUsed from "../components/AnswersUsed.jsx";

function mock(rows) {
  const state = { rows };
  global.fetch = vi.fn((url, opts) => {
    const u = String(url);
    if (u.includes("/review")) {
      const b = JSON.parse(opts.body);
      state.rows = state.rows.map((r) => (u.includes(`/${r.id}/`) ? { ...r, outcome: b.verdict === "wrong" ? "edited" : "kept" } : r));
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    }
    if (u.includes("/api/qbank/entries"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ entries: [{ id: "skill_years", question: "How many years of experience do you have with this skill?", topic: "experience" }] }) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ answers: state.rows }) });
  });
}
const ROW = { id: 4, label: "Years of Python?", answer: "2", source: "learned", retrieval_kind: "fts_fuzzy",
              retrieved_qkey: "years of java", retrieval_score: 0.6, outcome: null };

test("lists filled answers with the entry they came from; marking correct posts and shows the verdict", async () => {
  mock([ROW]);
  render(<AnswersUsed jobId={1} />);
  expect(await screen.findByText(/from “years of java” \(0.6\)/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Correct: Years of Python/ }));
  expect(await screen.findByText("marked correct")).toBeInTheDocument();
  const post = global.fetch.mock.calls.find(([u]) => String(u).includes("/application-qa/4/review"));
  expect(JSON.parse(post[1].body)).toMatchObject({ verdict: "correct" });
});

test("marking wrong lets you point it at the right questionnaire entry", async () => {
  mock([ROW]);
  render(<AnswersUsed jobId={1} />);
  fireEvent.click(await screen.findByRole("button", { name: /Wrong: Years of Python/ }));
  const picker = screen.getByLabelText(/Right question for Years of Python/);
  await waitFor(() => expect(global.fetch.mock.calls.some(([u]) => String(u).includes("/api/qbank/entries"))).toBe(true));
  fireEvent.change(picker, { target: { value: "How many years of experience do you have with this skill?" } });
  fireEvent.click(screen.getByRole("button", { name: "Save fix" }));
  await waitFor(() => {
    const post = global.fetch.mock.calls.find(([u]) => String(u).includes("/review"));
    expect(JSON.parse(post[1].body)).toEqual({ verdict: "wrong", entry_id: "skill_years" });
  });
  expect(await screen.findByText("marked wrong")).toBeInTheDocument();
});

test("renders nothing when the agent filled nothing", async () => {
  mock([]);
  const { container } = render(<AnswersUsed jobId={1} />);
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  expect(container.textContent).toBe("");
});

test("Save fix button is disabled until an entry is picked", async () => {
  mock([ROW]);
  render(<AnswersUsed jobId={1} />);
  fireEvent.click(await screen.findByRole("button", { name: /Wrong: Years of Python/ }));
  const saveBtn = screen.getByRole("button", { name: "Save fix" });
  expect(saveBtn).toBeDisabled();
  const picker = screen.getByLabelText(/Right question for Years of Python/);
  await waitFor(() => expect(global.fetch.mock.calls.some(([u]) => String(u).includes("/api/qbank/entries"))).toBe(true));
  fireEvent.change(picker, { target: { value: "How many years of experience do you have with this skill?" } });
  await waitFor(() => expect(saveBtn).not.toBeDisabled());
});
