import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, test, vi, beforeEach } from "vitest";
import TrackerBoard from "../components/TrackerBoard.jsx";

const BOARD = {
  saved: [], applied: [{ id: 2, title: "MLE", company: "Globex", status: "applied" }],
  failed: [{ id: 5, title: "AI Eng", company: "Genpact", status: "failed", queue_reason: "needs_answers" }],
  interviewing: [], offer: [], archived: [],
};

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    const body = String(url).includes("/api/tracker") ? BOARD
      : String(url).includes("/api/apply-agent/status") ? { running: false, job_id: null }
      : String(url).includes("/mail-scan/status") ? { running: false, last_scan: 0, connected: true, last_result: null }
      : {};
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("a failed job can be put back on the queue from the tracker; other jobs have no button", async () => {
  const onRequeue = vi.fn();
  render(<TrackerBoard onSelect={() => {}} refreshTick={0} onStatsChange={() => {}} onRequeue={onRequeue} />);
  const btn = await waitFor(() => screen.getByTestId("requeue-5"));
  expect(screen.queryByTestId("requeue-2")).toBeNull();
  fireEvent.click(btn);
  expect(onRequeue).toHaveBeenCalledWith(5);
});

test("the board re-reads itself, so a job marked applied elsewhere shows up without a reload", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let applied = [BOARD.applied[0]];
  global.fetch = vi.fn((url) => {
    const body = String(url).includes("/api/tracker") ? { ...BOARD, applied }
      : String(url).includes("/api/apply-agent/status") ? { running: false, job_id: null } : {};
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  const poll = vi.fn();
  render(<TrackerBoard onSelect={() => {}} refreshTick={0} onStatsChange={() => {}} onStatsPoll={poll} onRequeue={() => {}} />);
  await waitFor(() => expect(screen.getByText("Globex", { exact: false })).toBeInTheDocument());
  expect(screen.queryByText("Thales", { exact: false })).toBeNull();
  applied = [...applied, { id: 9, title: "Industrial Data Engineer", company: "Thales", status: "applied" }];   // marked applied by the watcher
  await vi.advanceTimersByTimeAsync(20500);
  await waitFor(() => expect(screen.getByText("Thales", { exact: false })).toBeInTheDocument());
  expect(poll).toHaveBeenCalled();                       // and the donut's counts were re-fetched with it
  vi.useRealTimers();
});
