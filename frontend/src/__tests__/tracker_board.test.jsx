import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, test, vi, beforeEach } from "vitest";
import TrackerBoard from "../components/TrackerBoard.jsx";

const BOARD = {
  saved: [{ id: 1, title: "DS", company: "Acme", industry: "BFSI", status: "saved" }],
  applied: [{ id: 2, title: "MLE", company: "Globex", status: "applied" }],
  interviewing: [], offer: [],
  archived: [{ id: 3, title: "AI", company: "Soylent", status: "rejected" }],
};

function mockFetch({ agentStatus = { running: false, job_id: null } } = {}) {
  return vi.fn((url, opts) => {
    const u = String(url);
    if (u.includes("/api/apply-agent/status"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(agentStatus) });
    if (u.includes("/api/tracker"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(BOARD) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
  });
}

beforeEach(() => {
  global.fetch = mockFetch();
});

function lastPatch() {
  const calls = global.fetch.mock.calls.filter(([, o]) => o && o.method === "PATCH");
  const [url, opts] = calls[calls.length - 1];
  return { url: String(url), body: JSON.parse(opts.body) };
}

test("renders rows (not columns) with a status pill, plus archived", async () => {
  render(<TrackerBoard onSelect={() => {}} />);
  expect(await screen.findByText("DS")).toBeInTheDocument();
  expect(screen.getByText("MLE")).toBeInTheDocument();
  expect(screen.getByTestId("status-pill-1")).toHaveTextContent("Saved");
  expect(screen.getByTestId("status-pill-2")).toHaveTextContent("Applied");
  expect(screen.queryByTestId("col-interviewing")).toBeNull(); // no column layout anymore
  expect(screen.getByText("AI")).toBeInTheDocument(); // inside the archived <details>
});

test("changing the stage select patches to that stage", async () => {
  render(<TrackerBoard onSelect={() => {}} />);
  await screen.findByText("DS");
  fireEvent.change(screen.getByTestId("stage-1"), { target: { value: "interviewing" } });
  await waitFor(() => {
    const p = lastPatch();
    expect(p.url).toContain("/api/jobs/1/status");
    expect(p.body.status).toBe("interviewing");
  });
});

test("select Remove untracks via status null", async () => {
  render(<TrackerBoard onSelect={() => {}} />);
  await screen.findByText("DS");
  fireEvent.change(screen.getByTestId("stage-1"), { target: { value: "__remove__" } });
  await waitFor(() => {
    const p = lastPatch();
    expect(p.url).toContain("/api/jobs/1/status");
    expect(p.body.status).toBe(null);
  });
});

test("a row for the currently-running job shows a live Filling tag instead of its stage pill", async () => {
  global.fetch = mockFetch({ agentStatus: { running: true, job_id: 1, title: "Application form" } });
  render(<TrackerBoard onSelect={() => {}} />);
  await screen.findByText("DS");
  await waitFor(() =>
    expect(screen.getByTestId("status-pill-1")).toHaveTextContent("Filling — Application form"));
  // job 2 isn't the running one -> still shows its normal stage pill
  expect(screen.getByTestId("status-pill-2")).toHaveTextContent("Applied");
});

test("clicking a row selects it, but clicking the stage select does not", async () => {
  const onSelect = vi.fn();
  render(<TrackerBoard onSelect={onSelect} />);
  await screen.findByText("DS");
  fireEvent.click(screen.getByTestId("stage-1"));
  expect(onSelect).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("DS"));
  expect(onSelect).toHaveBeenCalledWith(1);
});
