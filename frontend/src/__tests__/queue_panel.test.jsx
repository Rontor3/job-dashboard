import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import QueuePanel from "../components/QueuePanel.jsx";

const ITEMS = [
  { job_id: 1, title: "ML Eng", company: "Acme", state: "done", reason: "submitted" },
  { job_id: 2, title: "Data Eng", company: "Foo", state: "queued", reason: null },
  { job_id: 3, title: "AI Eng", company: "Bar", state: "queued", reason: null },
  { job_id: 4, title: "SWE", company: "Baz", state: "parked", reason: "needs_answers" },
];

let calls;
beforeEach(() => {
  calls = [];
  global.fetch = vi.fn((url, opts = {}) => {
    calls.push([String(url), opts.method || "GET", opts.body ? JSON.parse(opts.body) : null]);
    const body = String(url).includes("autosubmit")
      ? { naukri: false, career_site: true }
      : { items: ITEMS, running: false, paused: false };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("lists jobs with queue numbers, states and reasons", () => {
  render(<QueuePanel queue={{ items: ITEMS }} onChange={() => {}} />);
  expect(screen.getByTestId("queue-item-2").textContent).toContain("1");
  expect(screen.getByTestId("queue-item-3").textContent).toContain("2");
  expect(screen.getByTestId("queue-item-4").textContent).toContain("questions to answer");
  expect(screen.getByText(/1 parked/)).toBeInTheDocument();
});

test("move down places the job before the one after next; up before the previous", () => {
  const onChange = vi.fn((p) => p);
  render(<QueuePanel queue={{ items: ITEMS }} onChange={onChange} />);
  fireEvent.click(screen.getByLabelText("Move 2 down"));
  fireEvent.click(screen.getByLabelText("Move 3 up"));
  expect(calls).toEqual([
    ["/api/queue/2/move", "POST", { before: null }],
    ["/api/queue/3/move", "POST", { before: 2 }],
  ]);
  expect(screen.getByLabelText("Move 2 up")).toBeDisabled();
});

test("start, pause and remove call the API", () => {
  const onChange = vi.fn((p) => p);
  const { rerender } = render(<QueuePanel queue={{ items: ITEMS }} onChange={onChange} />);
  fireEvent.click(screen.getByRole("button", { name: /start/i }));
  fireEvent.click(screen.getByLabelText("Remove 4"));
  rerender(<QueuePanel queue={{ items: ITEMS, running: true, paused: false }} onChange={onChange} />);
  fireEvent.click(screen.getByRole("button", { name: /pause/i }));
  expect(calls.map((c) => c.slice(0, 2))).toEqual([
    ["/api/queue/start", "POST"], ["/api/queue/4", "DELETE"], ["/api/queue/pause", "POST"],
  ]);
});

test("Start is disabled with nothing queued", () => {
  render(<QueuePanel queue={{ items: [ITEMS[0]] }} onChange={() => {}} />);
  expect(screen.getByRole("button", { name: /start/i })).toBeDisabled();
});

test("auto-submit toggles load on open and save per board", async () => {
  render(<QueuePanel queue={{ items: [] }} onChange={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: /auto-submit/i }));
  const naukri = await screen.findByLabelText("Auto-submit on Naukri");
  expect(naukri).not.toBeChecked();
  expect(screen.getByLabelText("Auto-submit on Company sites")).toBeChecked();
  fireEvent.click(naukri);
  await waitFor(() => expect(calls.at(-1)).toEqual(["/api/queue/autosubmit", "PUT", { board: "naukri", on: true }]));
});
