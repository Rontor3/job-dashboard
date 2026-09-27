import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import AnswersTab from "../components/AnswersTab.jsx";

const DATA = { unanswered: 1, answers: [
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

test("groups by topic, shows unanswered count, profile values and rule help", async () => {
  mock();
  render(<AnswersTab />);
  expect(await screen.findByText("1 unanswered")).toBeInTheDocument();
  expect(screen.getByText("Work authorization")).toBeInTheDocument();
  expect(screen.getByText(/from your profile \(gender\)/)).toBeInTheDocument();
  expect(screen.getByText("Male")).toBeInTheDocument();
  expect(screen.getByText(/comma-separated/)).toBeInTheDocument();
  expect(screen.getByText(/asked in 2 applications/)).toBeInTheDocument();
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

test("only-unanswered hides answered and profile entries", async () => {
  mock();
  render(<AnswersTab />);
  await screen.findByText("What is your gender?");
  fireEvent.click(screen.getByLabelText("Only unanswered"));
  expect(screen.queryByText("What is your gender?")).toBeNull();
  expect(screen.queryByText("Have you interviewed with this company before?")).toBeNull();
  expect(screen.getByText("Will you require visa sponsorship?")).toBeInTheDocument();
});

test("remove asks first, then DELETEs by entry id", async () => {
  const calls = mock();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<AnswersTab />);
  await screen.findByText("What is your gender?");
  fireEvent.click(screen.getByRole("button", { name: "Remove What is your gender?" }));
  await waitFor(() => expect(calls.some(([u, o]) => o && o.method === "DELETE" && u.includes("entry_id=gender"))).toBe(true));
});

test("both thresholds are editable", async () => {
  mock();
  render(<AnswersTab />);
  expect((await screen.findByLabelText(/Minimum match score/)).value).toBe("80");
  expect(screen.getByLabelText(/Minimum confidence to fill a generated answer/).value).toBe("60");
});
