import { fireEvent, render, screen } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import Feed from "../components/Feed.jsx";
import FilterBar from "../components/FilterBar.jsx";

const JOBS = [
  { id: 1, title: "ML Engineer", company: "Stripe", location: "Remote", source: "remotive",
    posted_date: "2026-07-11", embed_score: 0.87, llm_score: 87, verdict: "Strong Fit", status: null },
  { id: 2, title: "AI Engineer", company: "Acme", location: "Remote", source: "jobspy:linkedin",
    posted_date: "2026-07-12", embed_score: 0.76, llm_score: null, verdict: null, status: "applied" },
];

test("renders rows with verdict pill, ranking placeholder, and status chip", () => {
  render(<Feed jobs={JOBS} selectedId={null} onSelect={() => {}} />);
  expect(screen.getByText("Strong Fit")).toBeDefined();
  expect(screen.getByText("Ranking…")).toBeDefined();
  expect(screen.getByText(/applied/)).toBeDefined();
});

test("clicking a row selects it", () => {
  const onSelect = vi.fn();
  render(<Feed jobs={JOBS} selectedId={null} onSelect={onSelect} />);
  fireEvent.click(screen.getByText("ML Engineer"));
  expect(onSelect).toHaveBeenCalledWith(1);
});

test("rows get staggered animation delays", () => {
  render(<Feed jobs={JOBS} selectedId={null} onSelect={() => {}} />);
  const rows = screen.getAllByRole("listitem");
  expect(rows[0].style.animationDelay).toBe("0ms");
  expect(rows[1].style.animationDelay).toBe("80ms");
});

test("filter chips toggle and propagate", () => {
  const setFilters = vi.fn();
  render(<FilterBar filters={{ sort: "embed" }} setFilters={setFilters} />);
  fireEvent.click(screen.getByText("Remote"));
  expect(setFilters).toHaveBeenCalled();
  const updater = setFilters.mock.calls[0][0];
  expect(updater({ sort: "embed" })).toEqual({ sort: "embed", remote: true });
});
