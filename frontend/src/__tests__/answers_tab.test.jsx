import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import AnswersTab, { Tuning } from "../components/AnswersTab.jsx";

const DATA = { unanswered: 2, answers: [
  { id: "story_why_startups", question: "Why do you want to work at an early-stage startup?", topic: "story",
    atype: "text", answer: null, profile_ref: null, rule: null, rule_help: null, value: null,
    needs_input: true, wordings: [], asked_in: 0 },
  { id: "sponsorship_required", question: "Will you require visa sponsorship?", topic: "work_auth", atype: "bool",
    answer: null, profile_ref: null, rule: null, rule_help: null, value: null, needs_input: true,
    wordings: ["Will you require visa sponsorship?"], asked_in: 2 },
  { id: "gender", question: "What is your gender?", topic: "demographics", atype: "choice", answer: null,
    profile_ref: "gender", rule: null, rule_help: null, value: "Male", needs_input: false, wordings: ["Gender"], asked_in: 0 },
  { id: "interviewed_before", question: "Have you interviewed with this company before?", topic: "background",
    atype: "bool", answer: "none", profile_ref: null, rule: "company_in_list",
    rule_help: "Companies where the answer is Yes, comma-separated — or 'none'.", value: "none",
    needs_input: true, wordings: [], asked_in: 0 },
]};

function mock() {
  const calls = [];
  global.fetch = vi.fn((url, opts) => {
    const u = String(url);
    calls.push([u, opts]);
    const ok = (b) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(b) });
    if (u.includes("/api/agent-settings")) return ok({ answer_confidence_min: 60, qbank_confident_min: 80 });
    if (u.includes("/api/ingredients")) return ok({ units: [], skills_pool: [] });
    if (u.includes("/api/retrieval")) return ok({ total_fields: 0 });
    if (u.includes("/api/answers")) return ok(opts && opts.method ? { ok: true } : DATA);
    return ok({});
  });
  return calls;
}

beforeEach(() => { vi.restoreAllMocks(); });

test("opens on what needs filling, with a topic rail and counts", async () => {
  mock();
  render(<AnswersTab />);
  const rail = await screen.findByRole("navigation", { name: "Topics" });
  expect(rail).toHaveTextContent("To fill1");                          // the story entry lives under "Your story"
  expect(rail).toHaveTextContent("Work authorization0/1");
  expect(rail).not.toHaveTextContent("Your story");
  expect(screen.getByLabelText("Answer for Will you require visa sponsorship?")).toBeInTheDocument();
  expect(screen.queryByText("What is your gender?")).toBeNull();      // answered: in its topic, not in To fill
});

test("a topic shows its rows; a row opens to edit, with profile source and rule help", async () => {
  mock();
  render(<AnswersTab />);
  fireEvent.click(await screen.findByRole("button", { name: /Demographics/ }));
  expect(screen.getByText("Male")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /What is your gender\?/ }));
  expect(screen.getByDisplayValue("Male")).toBeInTheDocument();
  expect(screen.getByText(/From your profile \(gender\)/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Background/ }));
  fireEvent.click(screen.getByRole("button", { name: /interviewed with this company/ }));
  expect(screen.getByText(/comma-separated/)).toBeInTheDocument();
});

test("answering a yes/no entry PUTs entry_id and answer", async () => {
  const calls = mock();
  render(<AnswersTab />);
  fireEvent.change(await screen.findByLabelText("Answer for Will you require visa sponsorship?"), { target: { value: "Yes" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Will you require visa sponsorship?" }));
  await waitFor(() => {
    const put = calls.find(([u, o]) => u.includes("/api/answers") && o && o.method === "PUT");
    expect(JSON.parse(put[1].body)).toEqual({ entry_id: "sponsorship_required", answer: "Yes" });
  });
});

test("search spans every topic and groups the hits", async () => {
  mock();
  render(<AnswersTab />);
  fireEvent.change(await screen.findByLabelText("Search questions"), { target: { value: "gender" } });
  expect(await screen.findByRole("heading", { name: "Demographics (voluntary)" })).toBeInTheDocument();
});

test("remove asks first, then DELETEs by entry id", async () => {
  const calls = mock();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<AnswersTab />);
  fireEvent.click(await screen.findByRole("button", { name: /Demographics/ }));
  fireEvent.click(screen.getByRole("button", { name: /What is your gender\?/ }));
  fireEvent.click(screen.getByRole("button", { name: "Remove What is your gender?" }));
  await waitFor(() => expect(calls.some(([u, o]) => o && o.method === "DELETE" && u.includes("entry_id=gender"))).toBe(true));
});

test("both thresholds are editable under Tuning", async () => {
  mock();
  render(<Tuning />);
  expect(await screen.findByRole("radio", { name: /Balanced/ })).toHaveAttribute("aria-checked", "false");   // 80 is custom
  expect(screen.getByText("You've set your own numbers below.")).toBeInTheDocument();
  expect(screen.getByLabelText(/Minimum match score/).value).toBe("80");
  expect(screen.getByLabelText(/Minimum confidence to fill a generated answer/).value).toBe("60");
});

test("Your story shows only story entries, in a multi-line box", async () => {
  mock();
  render(<AnswersTab only="story" />);
  expect(await screen.findByText(/Not written yet/)).toBeInTheDocument();            // one line, not an open box
  fireEvent.click(screen.getByRole("button", { name: /Why do you want to work at an early-stage startup/ }));
  const box = await screen.findByLabelText("Answer for Why do you want to work at an early-stage startup?");
  expect(box.tagName).toBe("TEXTAREA");
  expect(screen.queryByText("Will you require visa sponsorship?")).toBeNull();
});

test("a profile-backed answer is editable and saves to the application profile", async () => {
  const calls = mock();
  render(<AnswersTab />);
  fireEvent.click(await screen.findByRole("button", { name: /Demographics/ }));
  fireEvent.click(screen.getByRole("button", { name: /What is your gender\?/ }));
  fireEvent.change(screen.getByLabelText("Answer for What is your gender?"), { target: { value: "Female" } });
  fireEvent.click(screen.getByRole("button", { name: "Save What is your gender?" }));
  await waitFor(() => {
    const put = calls.find(([u, o]) => u.includes("/api/application-profile") && o && o.method === "PUT");
    expect(JSON.parse(put[1].body)).toEqual({ gender: "Female" });
  });
});

test("an answer shows how many approvals it has earned toward autonomy", async () => {
  global.fetch = vi.fn((url, opts) => {
    const u = String(url);
    const ok = (b) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(b) });
    if (u.includes("/api/agent-settings")) return ok({ answer_confidence_min: 60, qbank_confident_min: 80 });
    if (u.includes("/api/ingredients")) return ok({ units: [], skills_pool: [] });
    if (u.includes("/api/retrieval")) return ok({ total_fields: 0 });
    if (u.includes("/api/answers")) return ok({ unanswered: 0, answers: [
      { id: "notice_period_text", question: "Notice period?", topic: "availability", atype: "text", answer: "30 days", profile_ref: null, rule: null, rule_help: null, value: "30 days", needs_input: true, wordings: [], asked_in: 4, approvals: 2 },
      { id: "age", question: "Are you 18+?", topic: "background", atype: "bool", answer: "Yes", profile_ref: null, rule: null, rule_help: null, value: "Yes", needs_input: true, wordings: [], asked_in: 9, approvals: 3 }] });
    return ok({});
  });
  render(<AnswersTab />);
  fireEvent.click(await screen.findByRole("button", { name: /Notice period\?/ }));
  expect(screen.getByTestId("approvals-notice_period_text")).toHaveTextContent("approved 2 of 3 times");
  fireEvent.click(screen.getByRole("button", { name: /Background/ }));
  expect(screen.getByText("✓ auto")).toBeInTheDocument();
});

test("Tuning in plain words: a preset sets both numbers at once", async () => {
  const calls = mock();
  render(<Tuning />);
  fireEvent.click(await screen.findByRole("radio", { name: /Careful/ }));
  await waitFor(() => expect(calls.some(([, o]) => o && o.method === "PUT" && /"qbank_confident_min":93/.test(o.body)
    && /"answer_confidence_min":75/.test(o.body))).toBe(true));
  expect(screen.getByRole("radio", { name: /Careful/ })).toHaveAttribute("aria-checked", "true");
});
