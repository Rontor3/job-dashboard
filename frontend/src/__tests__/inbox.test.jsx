import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import Inbox from "../components/Inbox.jsx";

let calls;
const BOX = {
  questions: [
    { row_id: 1, job_id: 9, title: "ML Eng", company: "Razorpay", label: "Notice period?", kind: "select",
      options: ["Immediate", "30 days"], guess: null },
    { row_id: 2, job_id: 9, title: "ML Eng", company: "Razorpay", label: "Why Razorpay?", kind: "textarea",
      options: [], guess: null },
  ],
  guesses: [{ row_id: 3, job_id: 9, title: "ML Eng", company: "Razorpay", label: "Years of Python?", answer: "5",
              source: "qbank_likely", matched: "years_python" }],
  bank: [],
};

beforeEach(() => {
  calls = [];
  global.fetch = vi.fn((url, opts = {}) => {
    calls.push([String(url), opts.method || "GET", opts.body && JSON.parse(opts.body)]);
    const body = String(url).includes("/api/inbox") ? BOX : { ok: true };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("one tap on an option answers a blocking question and saves it for every application", async () => {
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("button", { name: "30 days" }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.some(([u]) => u.includes("/questions/1/reply"))).toBe(true));
  const [, , body] = calls.find(([u]) => u.includes("/questions/1/reply"));
  expect(body).toEqual({ answer: "30 days", save_as: "new", entry_id: null });
  expect(await screen.findByText("Why Razorpay?")).toBeInTheDocument();     // next card
});

test("a question naming the company defaults to this application only", async () => {
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("button", { name: "Later" }));
  expect(await screen.findByText("Why Razorpay?")).toBeInTheDocument();
  expect(screen.getByLabelText("Use for every application")).not.toBeChecked();
});

test("confirming a guess teaches the match", async () => {
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("button", { name: "Later" }));
  fireEvent.click(await screen.findByRole("button", { name: "Later" }));
  fireEvent.click(await screen.findByRole("button", { name: "Looks right" }));
  await waitFor(() => expect(calls.some(([u, m, b]) => u.includes("/application-qa/3/review") && b.verdict === "correct")).toBe(true));
});

test("nothing waiting says so and points to jobs", async () => {
  global.fetch = vi.fn(() => Promise.resolve({ ok: true, status: 200,
    json: () => Promise.resolve({ questions: [], guesses: [], bank: [] }) }));
  const go = vi.fn();
  render(<Inbox onGoJobs={go} />);
  fireEvent.click(await screen.findByRole("button", { name: "Review jobs" }));
  expect(go).toHaveBeenCalled();
});

const RULE_BOX = { questions: [], guesses: [], bank: [
  { id: "applied_before", question: "Have you previously applied to this company?", atype: "bool", asked_in: 0,
    asked_by: [], rule: "company_in_list", rule_help: "Companies where the answer is Yes, comma-separated — or 'none'." },
  { id: "ai_policy_ack", question: "Do you acknowledge our policy on using AI in this application?", atype: "bool",
    asked_in: 2, asked_by: ["Anthropic", "Acme"], rule: null, rule_help: null },
] };

function serve(box, explanation = "They want you to confirm you read their AI-use rules.") {
  global.fetch = vi.fn((url, opts = {}) => {
    calls.push([String(url), opts.method || "GET", opts.body && JSON.parse(opts.body)]);
    const body = String(url).includes("/api/inbox") ? box : String(url).includes("/api/explain") ? { explanation } : { ok: true };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
}

test("a per-company rule question asks for the list, not a bare Yes/No", async () => {
  serve(RULE_BOX);
  render(<Inbox />);
  expect(await screen.findByText(/Companies where the answer is Yes/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Yes" })).toBeNull();
  expect(screen.getByLabelText("Your answer")).toBeInTheDocument();
  expect(screen.getByText(/None of your applications has asked it yet/)).toBeInTheDocument();
});

test("says which applications asked, explains on request, and allows a typed answer", async () => {
  serve(RULE_BOX);
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("button", { name: "Later" }));
  expect(await screen.findByText("Asked by Anthropic, Acme")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "What does this mean?" }));
  expect(await screen.findByRole("note")).toHaveTextContent("confirm you read their AI-use rules");
  expect(calls.find(([u]) => u.includes("/api/explain"))[2].options).toEqual(["Yes", "No"]);
  fireEvent.click(screen.getByRole("button", { name: "Type my own answer" }));
  fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "Yes, I've read it" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.some(([u, m, b]) => u.endsWith("/api/answers") && b.answer === "Yes, I've read it")).toBe(true));
});
