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

test("shows the résumé-fit reason", async () => {
  POSTS.posts[0].fit_reason = "Strong GenAI overlap";
  render(<HiringSignals />);
  await waitFor(() => expect(screen.getByText(/Strong GenAI overlap/)).toBeInTheDocument());
});

test("card buttons follow research state", async () => {
  POSTS.posts[0] = { ...POSTS.posts[0], contacts: { emails: ["a@acme.ai"], forms: [], links: [], phones: [], dm: false }, job_id: null };
  const { unmount } = render(<HiringSignals />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Research company" })).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "Draft email" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Create CV" })).toBeNull();   // only the user's own PDF is sent
  unmount();
  POSTS.posts[0] = { ...POSTS.posts[0], job_id: 7, resume_id: 3 };
  render(<HiringSignals />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Draft email" })).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "Research company" })).toBeNull();
});

test("status badge, mark/undo, and draft warning", async () => {
  const base = { ...POSTS.posts[0], contacts: { emails: ["a@acme.ai"], forms: [], links: [], phones: [], dm: false }, job_id: 7 };
  const calls = [];
  let current = { ...base, status: null };
  global.fetch = vi.fn((url, opts) => {
    if (String(url).includes("/status")) { calls.push(JSON.parse(opts.body).status); current = { ...current, status: JSON.parse(opts.body).status }; return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) }); }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ posts: [current] }) });
  });
  render(<HiringSignals />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Draft email" })).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Mark applied" }));
  await waitFor(() => expect(screen.getByText("✓ Applied")).toBeInTheDocument());
  expect(calls).toEqual(["applied"]);
  expect(screen.queryByRole("button", { name: "Draft email" })).toBeNull();      // done → no primary action
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Draft email" })).toBeInTheDocument());
  expect(calls).toEqual(["applied", null]);
});

test("drafted post offers Mark emailed and Draft again", async () => {
  global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ posts: [{
    ...POSTS.posts[0], contacts: { emails: ["a@acme.ai"], forms: [], links: [], phones: [], dm: false }, job_id: 7, status: "drafted" }] }) }));
  render(<HiringSignals />);
  await waitFor(() => expect(screen.getByText("Draft created")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Mark emailed" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Draft again" })).toBeInTheDocument();
});
