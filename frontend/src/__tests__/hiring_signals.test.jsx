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
  expect(screen.getByRole("button", { name: "Create CV" })).toBeInTheDocument();
  unmount();
  POSTS.posts[0] = { ...POSTS.posts[0], job_id: 7, resume_id: 3 };
  render(<HiringSignals />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Draft email" })).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "Research company" })).toBeNull();
  expect(screen.getByText("CV ↗").getAttribute("href")).toBe("/api/resumes/3/pdf");
});
