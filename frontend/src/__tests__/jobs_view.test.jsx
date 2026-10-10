import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import JobsView from "../components/JobsView.jsx";

let calls, prefs;
beforeEach(() => {
  calls = [];
  prefs = { likes: [{ feature: "title:llm", label: "llm", weight: 1 }], dislikes: [], blocked_companies: [],
            skip_reasons: [{ key: "location", label: "Location" }, { key: "role", label: "Wrong role" }] };
  global.fetch = vi.fn((url, opts = {}) => {
    const u = String(url);
    calls.push([u, opts.method || "GET", opts.body && JSON.parse(opts.body)]);
    const body = u.includes("/api/company-details") ? (opts.method === "PUT" ? { company: "Sarvam", details: { referrer: "Jane" } }
        : { companies: { phonepe: { company: "PhonePe", details: { applied_before: true } } } })
      : u.includes("/api/preferences") ? prefs
      : u.includes("/feedback") ? prefs
      : { jobs: [{ id: 1, title: "LLM Engineer", company: "Sarvam", location: "Bengaluru", llm_score: 84, pref: 6 },
                 { id: 2, title: "Data Scientist", company: "PhonePe", location: "Pune", llm_score: 63, pref: 0 },
                 { id: 3, title: "ML Platform Engineer", company: "sarvam ", location: "Bengaluru", llm_score: 71, pref: 0 }], total: 3 };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("asks the API for the learned ranking and shows what was learned", async () => {
  render(<JobsView onApply={() => {}} onOpen={() => {}} />);
  expect(await screen.findByText("LLM Engineer")).toBeInTheDocument();
  expect(calls.some(([u]) => u.includes("sort=learned"))).toBe(true);
  expect(screen.getByLabelText("What the agent learned")).toHaveTextContent("llm");
  expect(screen.getByText(/you/)).toBeInTheDocument();          // the ↑ marker on a learned boost
});

test("skip asks why, and one tap sends the reason and drops the row", async () => {
  render(<JobsView onApply={() => {}} onOpen={() => {}} />);
  await screen.findByText("Data Scientist");
  fireEvent.click(within(screen.getByRole("listitem", { name: "PhonePe" })).getByRole("button", { name: "Skip" }));
  fireEvent.click(screen.getByRole("button", { name: "Location" }));
  expect(screen.queryByText("Data Scientist")).toBeNull();
  await waitFor(() => expect(calls.some(([u, m, b]) => u.includes("/api/jobs/2/feedback")
    && b.verdict === "skip" && b.reasons[0] === "location")).toBe(true));
});

test("apply hands the job to the queue", async () => {
  const apply = vi.fn();
  render(<JobsView onApply={apply} onOpen={() => {}} />);
  await screen.findByText("LLM Engineer");
  fireEvent.click(screen.getAllByRole("button", { name: "Apply" })[0]);
  expect(apply).toHaveBeenCalledWith(1);
});

test("a learned preference can be forgotten", async () => {
  render(<JobsView onApply={() => {}} onOpen={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: "Forget llm" }));
  await waitFor(() => expect(calls.some(([u, m]) => u.includes("/api/preferences/title%3Allm") && m === "DELETE")).toBe(true));
});

test("tick jobs (or every strong fit) and apply to all of them in one go", async () => {
  const queued = vi.fn();
  render(<JobsView onApply={() => {}} onOpen={() => {}} onQueued={queued} />);
  await screen.findByText("LLM Engineer");
  fireEvent.click(screen.getByRole("button", { name: "Select strong fits (2)" }));
  expect(screen.getByLabelText("Select LLM Engineer at Sarvam")).toBeChecked();
  fireEvent.click(screen.getByLabelText("Select Data Scientist at PhonePe"));
  fireEvent.click(screen.getByRole("button", { name: "Apply to 3" }));
  await waitFor(() => expect(calls.some(([u, m, b]) => u.includes("/api/queue/batch") && m === "POST"
    && b.start === true && b.job_ids.join() === "1,2,3")).toBe(true));
});

test("jobs sent over from the Inbox arrive pre-selected, and only those are listed", async () => {
  render(<JobsView onApply={() => {}} onOpen={() => {}} focusIds={[2]} onClearFocus={() => {}} />);
  await screen.findByText("Data Scientist");
  expect(calls.some(([u]) => u.includes("ids=2"))).toBe(true);
  expect(screen.getByText("Showing 1 job from the Inbox")).toBeInTheDocument();
  expect(screen.getByLabelText("Select Data Scientist at PhonePe")).toBeChecked();
  expect(screen.getByRole("button", { name: "Apply to 1" })).toBeInTheDocument();
});

test("openings are grouped by company; the header ticks them all and holds what's true for every one", async () => {
  render(<JobsView onApply={() => {}} onOpen={() => {}} />);
  const sarvam = await screen.findByRole("listitem", { name: "Sarvam" });
  expect(within(sarvam).getByText("ML Platform Engineer")).toBeInTheDocument();          // "sarvam " is the same company
  expect(within(sarvam).getByText("2 openings · best fit 84")).toBeInTheDocument();
  expect(within(screen.getByRole("listitem", { name: "PhonePe" })).getByRole("button", { name: "applied before" })).toBeInTheDocument();
  fireEvent.click(within(sarvam).getByLabelText("Select every open role at Sarvam"));
  expect(screen.getByRole("button", { name: "Apply to 2" })).toBeInTheDocument();
  fireEvent.click(within(sarvam).getByRole("button", { name: /Referral, applied before/ }));
  fireEvent.change(within(sarvam).getByLabelText("Referred by"), { target: { value: "Jane" } });
  fireEvent.click(within(sarvam).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.some(([u, m, b]) => u === "/api/company-details" && m === "PUT"
    && b.company === "Sarvam" && b.details.referrer === "Jane")).toBe(true));
  expect(await within(sarvam).findByRole("button", { name: "referred by Jane" })).toBeInTheDocument();
});

test("strong fits only, and a flat list when you'd rather not group", async () => {
  render(<JobsView onApply={() => {}} onOpen={() => {}} />);
  await screen.findByText("Data Scientist");
  fireEvent.click(screen.getByRole("button", { name: "Strong fits only" }));
  expect(screen.queryByText("Data Scientist")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "By company" }));
  expect(screen.queryByRole("listitem", { name: "Sarvam" })).toBeNull();
  expect(screen.getByText("LLM Engineer")).toBeInTheDocument();
});
