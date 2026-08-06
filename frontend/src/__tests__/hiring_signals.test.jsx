import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import HiringSignals from "../components/HiringSignals.jsx";

const POSTS = { posts: [
  { id: 1, url: "https://li/1", poster_name: "Jane Doe", poster_headline: "EM @ Acme",
    text: "Hiring an ML Engineer!", posted_at: "5h", keyword: "hiring ML engineer",
    fit_score: 0.82 },
]};

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/refresh")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ ranked: 1 }) });
    if (String(url).includes("/dismiss")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    return Promise.resolve({ ok: true, json: () => Promise.resolve(POSTS) });
  });
});

test("lists posts with poster and blurb", async () => {
  render(<HiringSignals />);
  await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
  expect(screen.getByText(/Hiring an ML Engineer/)).toBeInTheDocument();
});

test("refresh triggers POST /refresh", async () => {
  render(<HiringSignals />);
  fireEvent.click(screen.getByRole("button", { name: /Refresh/i }));
  await waitFor(() =>
    expect(global.fetch.mock.calls.some(([u]) => String(u).includes("/refresh"))).toBe(true));
});

test("dismiss removes the card", async () => {
  render(<HiringSignals />);
  await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
  fireEvent.click(screen.getByLabelText("Dismiss"));
  await waitFor(() => expect(screen.queryByText("Jane Doe")).toBeNull());
});
