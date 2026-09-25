import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import AgentRunHistory from "../components/AgentRunHistory.jsx";

function mockFetch(status, body) {
  return vi.fn(() => Promise.resolve({
    ok: status !== 404,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(""),
  }));
}

beforeEach(() => {
  global.fetch = mockFetch(404, null);
});

test("renders nothing when no run has ever happened", async () => {
  const { container } = render(<AgentRunHistory jobId={1} />);
  await waitFor(() => expect(container.textContent).toBe(""));
});

test("stopped-mid-way run shows the stuck step highlighted with its reason", async () => {
  global.fetch = mockFetch(200, {
    job_id: 1,
    steps: [
      { step: 0, kind: "form", cred_action: null, stopped_reason: null,
        pending_human: [], gate_notice: null, screenshot: null },
      { step: 1, kind: "form", cred_action: null, stopped_reason: null,
        pending_human: [], gate_notice: null, screenshot: null },
      { step: 2, kind: "form", cred_action: null, stopped_reason: "stuck",
        pending_human: [{ ref: "why_us", label: "Why do you want to work here?" }],
        gate_notice: null, screenshot: "/api/jobs/1/agent-runs/screenshot/2" },
    ],
  });
  render(<AgentRunHistory jobId={1} />);
  await waitFor(() => expect(screen.getByText(/Page 3/)).toBeDefined());
  expect(screen.getByText(/didn't change after the last action/)).toBeDefined();
  expect(screen.getByText(/Why do you want to work here\?/)).toBeDefined();
  expect(screen.getByRole("img")).toHaveProperty("src", expect.stringContaining("/api/jobs/1/agent-runs/screenshot/2"));
});

test("clean finish (reached submit dry-run) is not flagged as stuck", async () => {
  global.fetch = mockFetch(200, {
    job_id: 1,
    steps: [
      { step: 0, kind: "form", cred_action: null, stopped_reason: "reached_submit_dry_run",
        pending_human: [], gate_notice: null, screenshot: null },
    ],
  });
  render(<AgentRunHistory jobId={1} />);
  await waitFor(() => expect(screen.getByText(/ready for you to review/i)).toBeDefined());
  expect(screen.queryByText(/didn't change/)).toBeNull();
});

test("gate_notice reports when Telegram was never attempted", async () => {
  global.fetch = mockFetch(200, {
    job_id: 1,
    steps: [
      { step: 0, kind: "form", cred_action: null, stopped_reason: "gate:otp_sms",
        pending_human: [], gate_notice: { gate: "otp_sms", attempted: false, sent: false, resolved: false },
        screenshot: null },
    ],
  });
  render(<AgentRunHistory jobId={1} />);
  await waitFor(() => expect(screen.getByText(/not notified/i)).toBeDefined());
});

test("Run log loads lazily when expanded", async () => {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    if (u.includes("/agent-runs/log"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ lines: ["[gate] hcaptcha_image"] }) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ job_id: 1, steps: [
      { step: 0, kind: "form", cred_action: null, stopped_reason: "stuck", pending_human: [], gate_notice: null, screenshot: null } ] }) });
  });
  const { container } = render(<AgentRunHistory jobId={1} />);
  await waitFor(() => expect(screen.getByText("Run log")).toBeDefined());
  const details = container.querySelector("details");
  details.open = true;
  fireEvent(details, new Event("toggle"));
  await waitFor(() => expect(screen.getByText(/\[gate\] hcaptcha_image/)).toBeDefined());
});
