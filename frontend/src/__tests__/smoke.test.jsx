import { render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import App from "../App.jsx";

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    const body = String(url).includes("/api/stats")
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
  expect(screen.getByTestId("total").textContent).toBe("2");
});
