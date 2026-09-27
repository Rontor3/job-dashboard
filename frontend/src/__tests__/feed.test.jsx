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

const AGENT = { kind: "naukri", label: "Naukri", fill: "agent" };

test("each row offers Apply and + Queue for agent jobs, none for manual or applied ones", () => {
  const jobs = [
    { id: 1, title: "Naukri job", company: "Acme", status: null, apply_type: AGENT },
    { id: 2, title: "ATS job", company: "Acme", status: null, apply_type: { kind: "external-ats", label: "ATS form", fill: "easy" } },
    { id: 3, title: "Unknown flow", company: "Acme", status: null, apply_type: { kind: "other", label: "x", fill: "manual" } },
    { id: 4, title: "Done already", company: "Acme", status: "applied", apply_type: AGENT },
  ];
  render(<Feed jobs={jobs} selectedId={null} onSelect={() => {}} />);
  expect(screen.getAllByRole("button", { name: /^apply$/i })).toHaveLength(2);
  expect(screen.getAllByRole("button", { name: /add to queue/i })).toHaveLength(2);
});

test("Apply and + Queue call their handlers without selecting the row", () => {
  const onApply = vi.fn(); const onQueue = vi.fn(); const onSelect = vi.fn();
  const jobs = [{ id: 1, title: "Naukri job", company: "Acme", status: null, apply_type: AGENT }];
  render(<Feed jobs={jobs} selectedId={null} onSelect={onSelect} onApply={onApply} onQueue={onQueue} />);
  fireEvent.click(screen.getByRole("button", { name: /^apply$/i }));
  fireEvent.click(screen.getByRole("button", { name: /add to queue/i }));
  expect(onApply).toHaveBeenCalledWith(1);
  expect(onQueue).toHaveBeenCalledWith(1);
  expect(onSelect).not.toHaveBeenCalled();
});

test("a queued job shows its place and cannot be queued twice", () => {
  const onQueue = vi.fn();
  const jobs = [{ id: 1, title: "A", company: "Acme", status: "saved", apply_type: AGENT },
                { id: 2, title: "B", company: "Acme", status: "saved", apply_type: AGENT }];
  const queue = { items: [{ job_id: 9, state: "running" }, { job_id: 2, state: "queued" }, { job_id: 1, state: "queued" }] };
  render(<Feed jobs={jobs} selectedId={null} onSelect={() => {}} onQueue={onQueue} queue={queue} />);
  expect(screen.getByRole("button", { name: "Queued ✓ #3" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Queued ✓ #2" }));
  expect(onQueue).not.toHaveBeenCalled();
});

test("the running job reads Filling… and its Apply is disabled", () => {
  const jobs = [{ id: 1, title: "A", company: "Acme", status: "saved", apply_type: AGENT }];
  render(<Feed jobs={jobs} selectedId={null} onSelect={() => {}} queue={{ items: [{ job_id: 1, state: "running" }] }} />);
  expect(screen.getByRole("button", { name: "Queued Filling…" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^apply$/i })).toBeDisabled();
});
