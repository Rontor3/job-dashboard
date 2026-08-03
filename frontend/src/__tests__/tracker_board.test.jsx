import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, test, vi, beforeEach } from "vitest";
import TrackerBoard from "../components/TrackerBoard.jsx";

const BOARD = {
  saved: [{ id: 1, title: "DS", company: "Acme", industry: "BFSI", status: "saved" }],
  applied: [{ id: 2, title: "MLE", company: "Globex", status: "applied" }],
  interviewing: [], offer: [],
  archived: [{ id: 3, title: "AI", company: "Soylent", status: "rejected" }],
};

beforeEach(() => {
  global.fetch = vi.fn((url) =>
    Promise.resolve({ ok: true, status: 200,
      json: () => Promise.resolve(String(url).includes("/api/tracker") ? BOARD : { ok: true }) }));
});

function lastPatch() {
  const calls = global.fetch.mock.calls.filter(([, o]) => o && o.method === "PATCH");
  const [url, opts] = calls[calls.length - 1];
  return { url: String(url), body: JSON.parse(opts.body) };
}

test("renders cards in columns and archived", async () => {
  render(<TrackerBoard onSelect={() => {}} />);
  expect(await screen.findByText("DS")).toBeInTheDocument();
  expect(screen.getByText("MLE")).toBeInTheDocument();
  expect(screen.getByText("AI")).toBeInTheDocument();
});

test("dropping a card on a column patches to that stage", async () => {
  render(<TrackerBoard onSelect={() => {}} />);
  await screen.findByText("DS");
  fireEvent.drop(screen.getByTestId("col-interviewing"), { dataTransfer: { getData: () => "1" } });
  await waitFor(() => {
    const p = lastPatch();
    expect(p.url).toContain("/api/jobs/1/status");
    expect(p.body.status).toBe("interviewing");
  });
});

test("select Remove untracks via status null", async () => {
  render(<TrackerBoard onSelect={() => {}} />);
  await screen.findByText("DS");
  fireEvent.change(screen.getByTestId("stage-1"), { target: { value: "__remove__" } });
  await waitFor(() => {
    const p = lastPatch();
    expect(p.url).toContain("/api/jobs/1/status");
    expect(p.body.status).toBe(null);
  });
});
