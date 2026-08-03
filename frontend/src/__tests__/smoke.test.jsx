import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import App from "../App.jsx";

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    const body = String(url).includes("/api/tracker")
      ? { saved: [], applied: [], interviewing: [], offer: [], archived: [] }
      : String(url).includes("/api/stats")
      ? { total: 2, new: 1, saved: 0, applied: 1, dismissed: 0, unranked: 1 }
      : { jobs: [{ id: 1, title: "ML Engineer", company: "Stripe" },
                 { id: 2, title: "AI Engineer", company: "Acme" }], total: 2 };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("renders feed and stats from the API", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByText(/ML Engineer/)).toBeDefined());
  expect(screen.getByTestId("stats").textContent).toContain("2 jobs");
});

test("switches between Browse and Tracker tabs", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: /tracker/i }));
  expect(await screen.findByText(/Archived/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /browse/i }));
  expect(screen.getByTestId("feed-slot")).toBeInTheDocument();
});
