import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import App from "../App.jsx";

const INBOX = {
  questions: [{ row_id: 7, job_id: 1, title: "ML Engineer", company: "Stripe", label: "Notice period?",
                kind: "select", options: ["Immediate", "30 days"], guess: null }],
  guesses: [], bank: [],
};

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    const body = u.includes("/api/inbox") ? INBOX
      : u.includes("/api/queue") ? { items: [], running: false }
      : u.includes("/api/preferences") ? { likes: [], dislikes: [], blocked_companies: [], skip_reasons: [] }
      : u.includes("/api/tracker") ? { saved: [], applied: [], failed: [], interviewing: [], offer: [], archived: [] }
      : { jobs: [{ id: 1, title: "ML Engineer", company: "Stripe", llm_score: 81 }], total: 1 };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("opens on what the agent needs, with a waiting count on the tab", async () => {
  render(<App />);
  expect(await screen.findByText("Notice period?")).toBeInTheDocument();
  expect(screen.getByLabelText("1 waiting")).toBeInTheDocument();
});

test("four destinations, no stats or filter wall", async () => {
  render(<App />);
  const nav = screen.getByRole("navigation", { name: "Sections" });
  expect(nav.querySelectorAll("button")).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: /^jobs$/i }));
  expect(await screen.findByText("Stripe")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Filters" })).toBeNull();
});

test("the queue strip appears only when there is queued work", async () => {
  render(<App />);
  await screen.findByText("Notice period?");
  expect(screen.queryByRole("status")).toBeNull();
});
