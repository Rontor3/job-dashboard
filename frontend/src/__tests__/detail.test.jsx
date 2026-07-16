import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import JobDetail from "../components/JobDetail.jsx";
import DuplicatesSection from "../components/DuplicatesSection.jsx";
import RefreshButton from "../components/RefreshButton.jsx";

const DETAIL = {
  id: 1, title: "ML Engineer", company: "Stripe", location: "Remote",
  job_url: "https://x.com/1", status: null, embed_score: 0.81, llm_score: 87,
  verdict: "Strong Fit", description: "Own fraud models end-to-end.",
  strengths: ["prod ML"], gaps: ["k8s"], flags: { expired: false },
  cross_listings: [{ id: 3, source: "remoteok", job_url: "https://r.ok/3" }],
};

beforeEach(() => {
  global.fetch = vi.fn((url, opts) => {
    if (opts && opts.method === "PATCH")
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    if (String(url).includes("/api/duplicates"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
        duplicates: [{ id: 3, title: "ML Engineer", company: "Stripe", source: "remoteok",
                       job_url: "https://r.ok/3", duplicate_of: 1, canonical_source: "remotive" }] }) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(DETAIL) });
  });
});

test("detail shows JD, scores, strengths/gaps, cross-listings", async () => {
  render(<JobDetail id={1} onStatusChange={() => {}} onClose={() => {}} />);
  await waitFor(() => expect(screen.getByText(/Own fraud models/)).toBeDefined());
  expect(screen.getByText("prod ML")).toBeDefined();
  expect(screen.getByText("k8s")).toBeDefined();
  expect(screen.getByText(/remoteok/)).toBeDefined();
});

test("status buttons PATCH and notify", async () => {
  const onStatusChange = vi.fn();
  render(<JobDetail id={1} onStatusChange={onStatusChange} onClose={() => {}} />);
  await waitFor(() => screen.getByText("Save"));
  fireEvent.click(screen.getByText("Save"));
  await waitFor(() => expect(onStatusChange).toHaveBeenCalled());
  const patchCall = global.fetch.mock.calls.find(([, o]) => o && o.method === "PATCH");
  expect(patchCall[0]).toBe("/api/jobs/1/status");
  expect(JSON.parse(patchCall[1].body)).toEqual({ status: "saved" });
});

test("duplicates section expands and has no delete button", async () => {
  render(<DuplicatesSection />);
  await waitFor(() => screen.getByText(/Suspected duplicates/));
  fireEvent.click(screen.getByText(/Suspected duplicates/));
  await waitFor(() => expect(screen.getByText(/duplicate of #1/)).toBeDefined());
  expect(screen.queryByText(/\bdelete\b/i)).toBeNull();
});

test("duplicates header reads 'kept safe, never deleted'", async () => {
  render(<DuplicatesSection />);
  await waitFor(() => expect(screen.getByText(/Suspected duplicates \(1\) — kept safe, never deleted/)).toBeDefined());
});

test("renders flags: deal-breakers pill and deadline pill", async () => {
  const detailWithFlags = {
    ...DETAIL,
    flags: { deal_breakers: ["visa sponsorship unavailable"], deadline: "2026-07-20", expired: false },
  };
  global.fetch = vi.fn((url, opts) => {
    if (opts && opts.method === "PATCH")
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    if (String(url).includes("/api/duplicates"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ duplicates: [] }) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(detailWithFlags) });
  });
  render(<JobDetail id={2} onStatusChange={() => {}} onClose={() => {}} />);
  await waitFor(() => expect(screen.getByText(/visa sponsorship unavailable/)).toBeDefined());
  expect(screen.getByText(/2026-07-20/)).toBeDefined();
});

test("clears stale error when a later fetch for a new id succeeds", async () => {
  global.fetch = vi.fn((url, opts) => {
    if (opts && opts.method === "PATCH")
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    if (String(url).includes("/api/jobs/1")) return Promise.reject(new Error("network fail"));
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(DETAIL) });
  });
  const { rerender } = render(<JobDetail id={1} onStatusChange={() => {}} onClose={() => {}} />);
  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined());
  rerender(<JobDetail id={2} onStatusChange={() => {}} onClose={() => {}} />);
  await waitFor(() => expect(screen.getByText(/Own fraud models/)).toBeDefined());
  expect(screen.queryByRole("alert")).toBeNull();
});

test("refresh button shows alert with backend error message on error stage", async () => {
  global.fetch = vi.fn((url, opts) => {
    if (opts && opts.method === "POST")
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ running: false, stage: "error", error: "boom", last_result: null }),
    });
  });
  render(<RefreshButton onDone={() => {}} />);
  fireEvent.click(screen.getByRole("button"));
  await waitFor(() => expect(screen.getByText(/boom/)).toBeDefined());
});
