import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import MailBar from "../components/MailBar.jsx";
import MailPanel from "../components/MailPanel.jsx";

let status, calls;
beforeEach(() => {
  calls = [];
  status = { running: false, last_scan: Math.floor(Date.now() / 1000) - 3 * 3600, connected: true,
             last_result: { scanned: 40, matched: 2, error: null } };
  global.fetch = vi.fn((url, opts = {}) => {
    calls.push([String(url), opts.method || "GET"]);
    const u = String(url);
    const body = u.includes("/mail-scan/status") ? status
      : u.includes("/mail-scan") ? { started: true }
      : u.includes("/api/jobs/7/mail") ? { mail: [
          { id: 1, category: "interview", round: 2, subject: "Interview invitation", summary: "Panel on Friday", received_at: 1700000000 },
          { id: 2, category: "acknowledgement", round: null, subject: "We got your application", summary: "", received_at: 1699000000 }] }
      : { mail: [] };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("shows when the inbox was last checked and the result", async () => {
  render(<MailBar />);
  expect(await screen.findByText(/Last checked 3 h ago/)).toBeInTheDocument();
  expect(screen.getByText(/2 new reply\(ies\) in 40 mails/)).toBeInTheDocument();
});

test("Check email starts a scan and shows progress", async () => {
  render(<MailBar />);
  const btn = await screen.findByRole("button", { name: "Check email" });
  fireEvent.click(btn);
  expect(await screen.findByRole("button", { name: "Checking inbox…" })).toBeDisabled();
  expect(calls).toContainEqual(["/api/mail-scan", "POST"]);
});

test("when a running scan finishes the tracker is told to reload", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  status = { ...status, running: true };
  const onChanged = vi.fn();
  render(<MailBar onChanged={onChanged} />);
  await screen.findByRole("button", { name: "Checking inbox…" });
  status = { ...status, running: false };
  await vi.advanceTimersByTimeAsync(2100);
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  vi.useRealTimers();
});

test("says so when Gmail is not connected", async () => {
  status = { running: false, last_scan: 0, connected: false, last_result: { error: "gmail_not_connected" } };
  render(<MailBar />);
  expect(await screen.findByText(/Gmail isn't connected/)).toBeInTheDocument();
  expect(screen.getByText(/Last checked never/)).toBeInTheDocument();
});

test("the panel lists the company's mail with category, round and summary; nothing when there is none", async () => {
  const { container, rerender } = render(<MailPanel jobId={7} />);
  expect(await screen.findByText("Interview · round 2")).toBeInTheDocument();
  expect(screen.getByText("Panel on Friday")).toBeInTheDocument();
  expect(screen.getByText("Received")).toBeInTheDocument();
  rerender(<MailPanel jobId={8} />);
  await waitFor(() => expect(container.textContent).toBe(""));
});
