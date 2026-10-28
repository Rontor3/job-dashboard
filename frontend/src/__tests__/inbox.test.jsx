import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import Inbox from "../components/Inbox.jsx";

let calls, interpretReply;
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

function serve(box) {
  global.fetch = vi.fn((url, opts = {}) => {
    const u = String(url);
    calls.push([u, opts.method || "GET", opts.body && JSON.parse(opts.body)]);
    const body = u.includes("/api/inbox?") || u.endsWith("/api/inbox") ? box
      : u.includes("/api/answers/interpret") ? interpretReply
      : { ok: true, submission: 1 };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
}
const heading = (name) => screen.findByRole("heading", { name });
const saved = (pred) => waitFor(() => expect(calls.some(pred)).toBe(true));

beforeEach(() => {
  calls = [];
  interpretReply = { answer: null, also: {}, request: null };
  serve(BOX);
});

test("a tap stages the answer and moves on; nothing is saved until Submit", async () => {
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("radio", { name: "30 days" }));
  expect(await heading("Why Razorpay?")).toBeInTheDocument();
  expect(calls.some(([u]) => u.includes("/reply"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Submit 1 answer" }));
  await saved(([u, , b]) => u.includes("/questions/1/reply") && b.answer === "30 days" && b.save_as === "new");
});

test("a question naming the company defaults to this application only", async () => {
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("button", { name: "Next question" }));
  expect(await heading("Why Razorpay?")).toBeInTheDocument();
  expect(screen.getByLabelText("Use for every application")).not.toBeChecked();
});

test("confirming a guess teaches the match once submitted", async () => {
  render(<Inbox />);
  await heading("Notice period?");
  fireEvent.click(within(screen.getByRole("list", { name: "All questions" })).getByRole("button", { name: /Years of Python/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Looks right" }));
  fireEvent.click(screen.getAllByRole("button", { name: "Submit 1 answer" })[0]);
  await saved(([u, , b]) => u.includes("/application-qa/3/review") && b.verdict === "correct");
});

test("a typed answer is read by the model: cleaned, and extra facts filled", async () => {
  interpretReply = { answer: "Machine Learning Engineer", also: { "qbank:current_employer": "Rephrase.ai" },
    request: "Read my title from LinkedIn next time." };
  serve({ questions: [], guesses: [], bank: [{ id: "current_title", question: "What is your current job title?", atype: "text",
    asked_in: 0, asked_by: [], rule: null, options: [] }] });
  render(<Inbox />);
  const box = await screen.findByLabelText("Your answer");
  fireEvent.change(box, { target: { value: "Machine learning engineer. Why weren't you able to scrape this from my LinkedIn?" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(await screen.findByText(/Ready to save 1 answer/)).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "Submit 1 answer" })[0]);
  await saved(([u, , b]) => u.endsWith("/api/answers") && b.entry_id === "current_title" && b.answer === "Machine Learning Engineer");
  await saved(([u, , b]) => u.endsWith("/api/profile/facts") && b.answers["qbank:current_employer"] === "Rephrase.ai");
});

test("nothing waiting says so and points to jobs", async () => {
  serve({ questions: [], guesses: [], bank: [] });
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

test("a per-company rule question asks for the list, not a bare Yes/No", async () => {
  serve(RULE_BOX);
  render(<Inbox />);
  expect(await screen.findByText(/Companies where the answer is Yes/)).toBeInTheDocument();
  expect(screen.queryByRole("radio", { name: "Yes" })).toBeNull();
  expect(screen.getByLabelText("Your answer")).toBeInTheDocument();
});

test("says which applications asked", async () => {
  serve(RULE_BOX);
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("button", { name: "Next question" }));
  expect(await screen.findByText("Asked by Anthropic, Acme")).toBeInTheDocument();
});

const BANK_BOX = { questions: [], guesses: [], bank: [
  { id: "sexual_orientation", question: "What is your sexual orientation?", atype: "choice", asked_in: 1, asked_by: ["Acme"],
    rule: null, options: ["Heterosexual / straight", "Gay or lesbian", "Prefer not to say"] },
  { id: "transgender", question: "Do you identify as transgender?", atype: "bool", asked_in: 1, asked_by: ["Acme"], rule: null },
  { id: "pronouns", question: "What are your pronouns?", atype: "text", asked_in: 1, asked_by: ["Acme"], rule: null },
] };

test("Back shows what you picked and lets you change it before submitting", async () => {
  serve(BANK_BOX);
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("radio", { name: "Prefer not to say" }));
  expect(await heading("Do you identify as transgender?")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Previous question" }));
  expect(screen.getByRole("radio", { name: "Prefer not to say" })).toHaveAttribute("aria-checked", "true");
  fireEvent.click(screen.getByRole("radio", { name: "Gay or lesbian" }));
  fireEvent.click(screen.getAllByRole("button", { name: "Submit 1 answer" })[0]);
  await saved(([, , b]) => b?.entry_id === "sexual_orientation" && b.answer === "Gay or lesbian");
  expect(calls.some(([, , b]) => b?.answer === "Prefer not to say")).toBe(false);
});

test("Submit snoozes what you skipped, so it stops coming back", async () => {
  serve(BANK_BOX);
  render(<Inbox />);
  fireEvent.click(await screen.findByRole("radio", { name: "Prefer not to say" }));
  fireEvent.click(screen.getAllByRole("button", { name: "Submit 1 answer" })[0]);
  await saved(([u, , b]) => u.endsWith("/api/inbox/snooze") && b.keys.join() === "btransgender,bpronouns");
});

test("keyboard: a number picks a choice, the arrows move, Enter takes a typed answer, the end is a review", async () => {
  serve(BANK_BOX);
  render(<Inbox />);
  await heading("What is your sexual orientation?");
  fireEvent.keyDown(window, { key: "ArrowRight" });
  expect(await heading("Do you identify as transgender?")).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "2" });
  const box = await screen.findByLabelText("Your answer");
  fireEvent.change(box, { target: { value: "he/him" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(await screen.findByText(/Ready to save 2 answers/)).toBeInTheDocument();
  expect(document.querySelector(".review-list")).toHaveTextContent("he/him");
});

test("the list beside the card jumps to any question", async () => {
  serve(BANK_BOX);
  render(<Inbox />);
  await heading("What is your sexual orientation?");
  fireEvent.click(within(screen.getByRole("list", { name: "All questions" })).getByRole("button", { name: /pronouns/ }));
  expect(await screen.findByLabelText("Your answer")).toBeInTheDocument();
  expect(screen.getByText("3 of 3")).toBeInTheDocument();
});

test("a profile must-have is saved to the profile, not the question bank", async () => {
  interpretReply = { answer: "60 days", also: {}, request: null };
  serve({ questions: [], guesses: [], bank: [{ id: "profile:notice_period", question: "What is your notice period?", atype: "text",
    asked_in: 0, asked_by: [], rule: null, options: [], fact: "profile:notice_period" }] });
  render(<Inbox />);
  const box = await screen.findByLabelText("Your answer");
  fireEvent.change(box, { target: { value: "two months" } });
  fireEvent.keyDown(box, { key: "Enter" });
  fireEvent.click((await screen.findAllByRole("button", { name: "Submit 1 answer" }))[0]);
  await saved(([u, , b]) => u.endsWith("/api/profile/facts") && b.answers["profile:notice_period"] === "60 days");
  expect(calls.some(([u]) => u.endsWith("/api/answers"))).toBe(false);
});

test("a typed answer is read in the background: you move on at once, and a follow-up comes back after the current one", async () => {
  let release;
  global.fetch = vi.fn((url, opts = {}) => {
    const u = String(url);
    calls.push([u, opts.method || "GET", opts.body && JSON.parse(opts.body)]);
    if (u.includes("/api/answers/interpret")) {
      return new Promise((res) => { release = () => res({ ok: true, status: 200, json: () => Promise.resolve(
        { answer: null, also: {}, request: "Read it from my LinkedIn." }) }); });
    }
    const body = u.includes("/api/inbox") ? BANK_BOX : { ok: true };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  render(<Inbox />);
  fireEvent.click(within(await screen.findByRole("list", { name: "All questions" })).getByRole("button", { name: /pronouns/ }));
  const box = await screen.findByLabelText("Your answer");
  fireEvent.change(box, { target: { value: "ask my LinkedIn" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(await screen.findByText(/Ready to save/)).toBeInTheDocument();              // not blocked on the model
  fireEvent.click(within(document.querySelector(".review-list")).getByRole("button", { name: "Do you identify as transgender?" }));
  release();
  await waitFor(() => expect(document.querySelector('.deck-item[data-state="again"]')).toHaveTextContent("pronouns"));
  expect(await heading("Do you identify as transgender?")).toBeInTheDocument();      // the current one stays put
  fireEvent.click(screen.getByRole("radio", { name: "No" }));
  expect(await heading("What are your pronouns?")).toBeInTheDocument();             // then the follow-up
  expect(screen.getByText(/What's the answer itself/)).toBeInTheDocument();
});
