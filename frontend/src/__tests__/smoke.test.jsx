import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import App from "../App.jsx";

const INBOX = {
  questions: [{ row_id: 7, job_id: 1, title: "ML Engineer", company: "Stripe", label: "Notice period?",
                kind: "select", options: ["Immediate", "30 days"], guess: null }],
  guesses: [], bank: [],
};

const NOTES = [{ id: 4, at: new Date().toISOString(), kind: "matches", level: "action", title: "3 strong new matches",
  body: null, job_id: null, data: { job_ids: [1, 2, 3] }, source: "refresh", read_at: null }];

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  global.fetch = vi.fn((url) => {
    const u = String(url);
    const body = u.includes("/api/inbox") ? INBOX
      : u.includes("/api/setup-state") ? { exists: true, status: "complete" }
      : u.includes("/agent/sessions") ? { active: null, items: [] }
      : u.includes("/api/queue") ? { items: [], running: false }
      : u.includes("/api/preferences") ? { likes: [], dislikes: [], blocked_companies: [], skip_reasons: [] }
      : u.includes("/api/tracker") ? { saved: [], applied: [], failed: [], interviewing: [], offer: [], archived: [] }
      : u.includes("/api/notifications") ? { items: NOTES, unread: NOTES.length }
      : u.includes("/agent/profiles") ? { profiles: [{ name: "scout", description: "Finds jobs", source: "base" }] }
      : { jobs: [{ id: 1, title: "ML Engineer", company: "Stripe", llm_score: 81 }], total: 1 };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("opens on the agents, with missions to hand off and the Inbox count on its tab", async () => {
  render(<App />);
  expect(await screen.findByRole("heading", { name: "What should the agents do?" })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: /Find my next jobs/ }).length).toBeGreaterThan(0);
  expect(await screen.findByLabelText("1 waiting, 1 new")).toBeInTheDocument();
});

test("the Inbox shows what blocks applications, then updates you can act on", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: /^Inbox/ }));
  expect(await screen.findByRole("heading", { name: "Notice period?" })).toBeInTheDocument();
  expect(await screen.findByText("3 strong new matches")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Apply to all 3" }));
  await waitFor(() => expect(global.fetch.mock.calls.some(([u, o]) => String(u).includes("/api/queue/batch")
    && JSON.parse(o.body).job_ids.length === 3)).toBe(true));
});

test("five destinations, no stats or filter wall", async () => {
  render(<App />);
  const nav = screen.getByRole("navigation", { name: "Sections" });
  expect(nav.querySelectorAll("button")).toHaveLength(5);
  fireEvent.click(screen.getByRole("button", { name: /^jobs$/i }));
  expect(await screen.findByText("Stripe")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Filters" })).toBeNull();
});

test("the queue strip appears only when there is queued work", async () => {
  render(<App />);
  await screen.findByRole("heading", { name: "What should the agents do?" });
  expect(document.querySelector(".strip")).toBeNull();
});

test("a reload reopens the tab you were on", async () => {
  const first = render(<App />);
  fireEvent.click(screen.getByRole("button", { name: /^jobs$/i }));
  expect(window.location.hash).toBe("#jobs");
  first.unmount();
  render(<App />);
  expect(screen.getByRole("button", { name: /^jobs$/i })).toHaveAttribute("aria-current", "page");
});
