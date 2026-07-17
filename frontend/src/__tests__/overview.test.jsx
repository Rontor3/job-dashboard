import { render, screen } from "@testing-library/react";
import { test, expect } from "vitest";
import Overview from "../components/Overview.jsx";

const STATS = { total: 30, new: 10, saved: 14, applied: 7,
                interviewing: 3, offer: 1, rejected: 2, dismissed: 3, unranked: 12 };

test("renders applications ring with applied count and goal", () => {
  render(<Overview stats={STATS} />);
  expect(screen.getAllByText("7").length).toBeGreaterThan(0);
  expect(screen.getByText(/Weekly goal: 10/)).toBeDefined();
});

test("renders a pipeline bar with count per stage", () => {
  render(<Overview stats={STATS} />);
  for (const [label, n] of [["Saved", "14"], ["Applied", "7"], ["Interviewing", "3"], ["Offer", "1"], ["Rejected", "2"]]) {
    expect(screen.getByText(label)).toBeDefined();
    expect(screen.getAllByText(n).length).toBeGreaterThan(0);
  }
});
