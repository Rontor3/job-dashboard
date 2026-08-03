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

test("min-score slider sets min_score as a 0-1 float, and 0 clears it", () => {
  const setFilters = vi.fn();
  render(<FilterBar filters={{ sort: "embed" }} setFilters={setFilters} />);
  const slider = screen.getByLabelText("Minimum match score");

  fireEvent.change(slider, { target: { value: "50" } });
  let updater = setFilters.mock.calls[setFilters.mock.calls.length - 1][0];
  expect(updater({ sort: "embed" }).min_score).toBe(0.5);

  fireEvent.change(slider, { target: { value: "0" } });
  updater = setFilters.mock.calls[setFilters.mock.calls.length - 1][0];
  expect(updater({ sort: "embed", min_score: 0.5 })).not.toHaveProperty("min_score");
});

test("source select sets filters.source", () => {
  const setFilters = vi.fn();
  render(<FilterBar filters={{ sort: "embed" }} setFilters={setFilters} />);
  fireEvent.change(screen.getByLabelText("Filter by source"), { target: { value: "remotive" } });
  const updater = setFilters.mock.calls[0][0];
  expect(updater({ sort: "embed" }).source).toBe("remotive");
});

test("shows + Track on untracked cards and calls onTrack without selecting", () => {
  const onTrack = vi.fn(); const onSelect = vi.fn();
  const jobs = [{ id: 1, title: "DS", company: "Acme", status: null }];
  render(<Feed jobs={jobs} selectedId={null} onSelect={onSelect} onTrack={onTrack} />);
  fireEvent.click(screen.getByRole("button", { name: /track/i }));
  expect(onTrack).toHaveBeenCalledWith(1);
  expect(onSelect).not.toHaveBeenCalled();
});
