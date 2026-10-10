import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import Inbox from "../components/Inbox.jsx";
import { AgentProvider } from "../agent/AgentProvider.tsx";
import Popover from "../agent/Popover.tsx";

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
  fireEvent.click(await screen.findByRole("radio", { name: "30 days" }));
  await waitFor(() => expect(calls.some(([u]) => u.includes("/questions/1/reply"))).toBe(true));
  const [, , body] = calls.find(([u]) => u.includes("/questions/1/reply"));
  expect(body).toEqual({ answer: "30 days", save_as: "new", entry_id: null });
  expect(await screen.findByRole("heading", { name: "Why Razorpay?" })).toBeInTheDocument();     // next card
});

test("a question naming the company defaults to this application only", async () => {
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("button", { name: "Next question" }));
  expect(await screen.findByRole("heading", { name: "Why Razorpay?" })).toBeInTheDocument();
  expect(screen.getByLabelText("Use for every application")).not.toBeChecked();
});

test("confirming a guess teaches the match", async () => {
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("button", { name: "Next question" }));
  fireEvent.click(await screen.findByRole("button", { name: "Next question" }));
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

function serve(box) {
  global.fetch = vi.fn((url, opts = {}) => {
    calls.push([String(url), opts.method || "GET", opts.body && JSON.parse(opts.body)]);
    const u = String(url);
    const body = u.includes("/api/inbox") ? box
      : u === "/agent/sessions" && (opts.method || "GET") === "GET" ? { active: "s1", items: [{ id: "s1", title: "x", createdAt: 0 }] }
      : { ok: true, submission: 1 };
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

test("says which applications asked, asks the agent in place, and allows a typed answer", async () => {
  serve(RULE_BOX);
  render(<AgentProvider tab="inbox"><Inbox /><Popover /></AgentProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Next question" }));
  expect(await screen.findByText("Asked by Anthropic, Acme")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "What does this mean?" }));
  expect(await screen.findByRole("dialog", { name: "Ask the agent" })).toBeInTheDocument();
  await waitFor(() => expect(calls.some(([u]) => u === "/agent/sessions/s1/messages")).toBe(true));
  const [, , sent] = calls.find(([u]) => u === "/agent/sessions/s1/messages");
  expect(sent.content).toBe("What does this mean?");
  expect(sent.context).toMatchObject({ anchor: "qbank:ai_policy_ack", tab: "inbox" });
  expect(sent.context.text).toContain("acknowledge our policy on using AI");
  fireEvent.click(screen.getByRole("button", { name: "Type my own answer" }));
  fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "Yes, I've read it" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.some(([u, m, b]) => u.endsWith("/api/answers") && b.answer === "Yes, I've read it")).toBe(true));
});

test("without the agent there is no explain link", async () => {
  serve(RULE_BOX);
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("button", { name: "Next question" }));
  await screen.findByText("Asked by Anthropic, Acme");
  expect(screen.queryByRole("button", { name: "What does this mean?" })).toBeNull();
});


const BANK_BOX = { questions: [], guesses: [], bank: [
  { id: "sexual_orientation", question: "What is your sexual orientation?", atype: "choice", asked_in: 0, asked_by: [],
    rule: null, options: ["Heterosexual / straight", "Gay or lesbian", "Prefer not to say"] },
  { id: "transgender", question: "Do you identify as transgender?", atype: "bool", asked_in: 0, asked_by: [], rule: null },
  { id: "pronouns", question: "What are your pronouns?", atype: "text", asked_in: 0, asked_by: [], rule: null },
] };

test("a choice question offers its usual answers; a tap saves and moves on, Back shows what you picked", async () => {
  serve(BANK_BOX);
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("radio", { name: "Prefer not to say" }));
  expect(await screen.findByRole("heading", { name: "Do you identify as transgender?" })).toBeInTheDocument();      // moved on by itself
  await waitFor(() => expect(calls.some(([u, m, b]) => u.endsWith("/api/answers") && m === "PUT"
    && b.entry_id === "sexual_orientation" && b.answer === "Prefer not to say")).toBe(true));
  expect(screen.getByText("2 of 3")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Previous question" }));
  expect(await screen.findByRole("heading", { name: "What is your sexual orientation?" })).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: "Prefer not to say" })).toHaveAttribute("aria-checked", "true");
  fireEvent.click(screen.getByRole("radio", { name: "Gay or lesbian" }));                        // change it
  await waitFor(() => expect(calls.some(([, , b]) => b?.entry_id === "sexual_orientation" && b.answer === "Gay or lesbian")).toBe(true));
  expect(await screen.findByRole("heading", { name: "Do you identify as transgender?" })).toBeInTheDocument();
});

test("keyboard: a number picks a choice, the arrows move, Enter saves a typed answer", async () => {
  serve(BANK_BOX);
  render(<Inbox />);
  await screen.findByRole("heading", { name: "What is your sexual orientation?" });
  fireEvent.keyDown(window, { key: "ArrowRight" });
  expect(await screen.findByRole("heading", { name: "Do you identify as transgender?" })).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "2" });                                                       // No
  await waitFor(() => expect(calls.some(([, , b]) => b?.entry_id === "transgender" && b.answer === "No")).toBe(true));
  const box = await screen.findByLabelText("Your answer");                                      // pronouns
  fireEvent.change(box, { target: { value: "he/him" } });
  fireEvent.keyDown(box, { key: "Enter" });
  await waitFor(() => expect(calls.some(([, , b]) => b?.entry_id === "pronouns" && b.answer === "he/him")).toBe(true));
  expect(await screen.findByRole("heading", { name: "What is your sexual orientation?" })).toBeInTheDocument();   // the skipped one
  fireEvent.keyDown(window, { key: "3" });
  expect(await screen.findByText("That's everything for now.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Review my answers/ }));
  expect(await screen.findByText(/Your answer:/)).toHaveTextContent("he/him");
});

test("the list beside the card jumps to any question", async () => {
  serve(BANK_BOX);
  render(<Inbox />);
  await screen.findByRole("heading", { name: "What is your sexual orientation?" });
  const list = screen.getByRole("list", { name: "All questions" });
  fireEvent.click(within(list).getByRole("button", { name: /pronouns/ }));
  expect(await screen.findByLabelText("Your answer")).toBeInTheDocument();
  expect(screen.getByText("3 of 3")).toBeInTheDocument();
});
