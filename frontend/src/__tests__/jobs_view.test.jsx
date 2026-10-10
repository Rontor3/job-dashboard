import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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
    const body = u.includes("/api/preferences") ? prefs
      : u.includes("/feedback") ? prefs
      : { jobs: [{ id: 1, title: "LLM Engineer", company: "Sarvam", location: "Bengaluru", llm_score: 84, pref: 6 },
                 { id: 2, title: "Data Scientist", company: "PhonePe", location: "Pune", llm_score: 63, pref: 0 }], total: 2 };
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
  fireEvent.click(screen.getAllByRole("button", { name: "Skip" })[1]);
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
