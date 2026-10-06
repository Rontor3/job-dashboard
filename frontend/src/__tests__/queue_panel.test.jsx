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
const queueCalls = () => calls.filter((c) => !c[0].includes("autosubmit") && !c[0].includes("/settings"));   // the panel also reads its switches on load
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
  expect(queueCalls()).toEqual([
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
  expect(queueCalls().map((c) => c.slice(0, 2))).toEqual([
    ["/api/queue/start", "POST"], ["/api/queue/4", "DELETE"], ["/api/queue/pause", "POST"],
  ]);
});

test("Start is disabled with nothing queued", () => {
  render(<QueuePanel queue={{ items: [ITEMS[0]] }} onChange={() => {}} />);
  expect(screen.getByRole("button", { name: /start/i })).toBeDisabled();
});

test("auto-submit switches load, show their state, and turning one ON asks first", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<QueuePanel queue={{ items: [] }} onChange={() => {}} />);
  const naukri = await screen.findByLabelText("Auto-submit on Naukri");
  expect(naukri).toHaveAttribute("role", "switch");
  expect(naukri).toHaveAttribute("aria-checked", "false");
  expect(screen.getByLabelText("Auto-submit on Company sites")).toHaveAttribute("aria-checked", "true");
  fireEvent.click(naukri);
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining("SUBMIT applications there without you reviewing"));
  await waitFor(() => expect(calls.at(-1)).toEqual(["/api/queue/autosubmit", "PUT", { board: "naukri", on: true }]));
});

test("declining the confirmation leaves auto-submit off; turning one OFF needs no confirmation", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<QueuePanel queue={{ items: [] }} onChange={() => {}} />);
  fireEvent.click(await screen.findByLabelText("Auto-submit on Naukri"));
  expect(calls.some(([u, m]) => u.includes("autosubmit") && m === "PUT")).toBe(false);
  confirm.mockClear();
  fireEvent.click(screen.getByLabelText("Auto-submit on Company sites"));            // ON -> OFF
  expect(confirm).not.toHaveBeenCalled();
  await waitFor(() => expect(calls.at(-1)).toEqual(["/api/queue/autosubmit", "PUT", { board: "career_site", on: false }]));
});

test("a status badge says whether anything auto-submits, even with the section collapsed", async () => {
  render(<QueuePanel queue={{ items: [] }} onChange={() => {}} />);
  expect(await screen.findByTestId("autosubmit-status")).toHaveTextContent(/Auto-submit ON: Company sites/);
  fireEvent.click(screen.getByRole("button", { name: /auto-submit & telegram/i }));      // collapse
  expect(screen.getByTestId("autosubmit-status")).toBeInTheDocument();
  global.fetch = vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ naukri: false }) }));
});

test("the Telegram wait loads, is clamped to 0-120 and saved on blur", async () => {
  global.fetch = vi.fn((url, opts = {}) => {
    calls.push([String(url), opts.method || "GET", opts.body ? JSON.parse(opts.body) : null]);
    const body = String(url).includes("settings") ? { telegram_wait_minutes: 10 }
      : String(url).includes("autosubmit") ? { naukri: false } : { items: [] };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  render(<QueuePanel queue={{ items: [] }} onChange={() => {}} />);
  const input = await screen.findByLabelText("Telegram wait minutes");
  expect(input.value).toBe("10");
  fireEvent.change(input, { target: { value: "999" } });
  fireEvent.blur(input);
  await waitFor(() => expect(calls.at(-1)).toEqual(["/api/queue/settings", "PUT", { telegram_wait_minutes: 120 }]));
  expect(input.value).toBe("120");
});

test("when no board auto-submits the badge says every application waits for review", async () => {
  global.fetch = vi.fn((url) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(
    String(url).includes("settings") ? { telegram_wait_minutes: 10 } : String(url).includes("autosubmit") ? { naukri: false, indeed: false } : { items: [] }) }));
  render(<QueuePanel queue={{ items: [] }} onChange={() => {}} />);
  expect(await screen.findByTestId("autosubmit-status")).toHaveTextContent("Auto-submit OFF — every application waits for your review");
});

test("the Gmail confirmation switch is off by default, saves on change, and says what it reads", async () => {
  global.fetch = vi.fn((url, opts = {}) => {
    calls.push([String(url), opts.method || "GET", opts.body ? JSON.parse(opts.body) : null]);
    const body = String(url).includes("settings") ? { telegram_wait_minutes: 10, gmail_confirmation_check: false }
      : String(url).includes("autosubmit") ? { naukri: false } : { items: [] };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  render(<QueuePanel queue={{ items: [] }} onChange={() => {}} />);
  const box = await screen.findByLabelText("Confirm submissions from Gmail");
  expect(box).not.toBeChecked();
  expect(screen.getByText(/subject, sender and date only/i)).toBeInTheDocument();
  fireEvent.click(box);
  await waitFor(() => expect(calls.at(-1)).toEqual(["/api/queue/settings", "PUT", { gmail_confirmation_check: true }]));
  expect(box).toBeChecked();
});

test("the reconcile button reports how many jobs it marked applied", async () => {
  global.fetch = vi.fn((url, opts = {}) => {
    calls.push([String(url), opts.method || "GET", opts.body ? JSON.parse(opts.body) : null]);
    const body = String(url).includes("reconcile") ? { emails: 7, matched: [{ job_id: 1 }, { job_id: 2 }], ambiguous: [{}], unmatched: 0 }
      : String(url).includes("settings") ? { telegram_wait_minutes: 10, gmail_confirmation_check: true }
      : String(url).includes("autosubmit") ? { naukri: false } : { items: [] };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  render(<QueuePanel queue={{ items: [] }} onChange={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: /Mark applied jobs from Gmail now/ }));
  expect(await screen.findByText(/Marked 2 applied, 1 need you to pick the job \(7 emails\)/)).toBeInTheDocument();
  expect(calls.find(([u]) => u.includes("reconcile"))[2]).toEqual({ days: 14, apply: true });
});
