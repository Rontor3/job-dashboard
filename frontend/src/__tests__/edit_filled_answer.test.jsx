import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, test, vi, beforeEach } from "vitest";
import AgentRunHistory from "../components/AgentRunHistory.jsx";

const RUN = { steps: [{ step: 0, kind: "form", url: "https://x", stopped_reason: null, pending_human: [],
  questions: [{ id: 11, label: "Notice period (days)?", answer: "30", origin: "saved", matched: "notice_period",
                unsupported_claims: [] },
              { id: 12, label: "Why us?", answer: "Because", origin: "model", unsupported_claims: [] }] }], unpaged: [] };
let put;

beforeEach(() => {
  put = null;
  global.fetch = vi.fn((url, opts) => {
    const u = String(url);
    if (u.includes("/answer") && opts && opts.method === "PUT") put = { u, body: JSON.parse(opts.body) };
    const body = u.includes("/agent-runs/latest") ? RUN : { ok: true };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("a filled answer can be edited and saved, including to the saved answer it came from", async () => {
  render(<AgentRunHistory jobId={5} />);
  fireEvent.click(await waitFor(() => screen.getByRole("button", { name: /edit: notice period/i })));
  const box = screen.getByLabelText(/edit answer: notice period/i);
  expect(box.value).toBe("30");
  fireEvent.change(box, { target: { value: "45" } });
  fireEvent.change(screen.getByLabelText(/where to save/i), { target: { value: "entry" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(put).not.toBeNull());
  expect(put.u).toContain("/api/application-qa/11/answer");
  expect(put.body).toEqual({ answer: "45", save_as: "entry" });
});

test("an answer not recalled from a saved one offers no 'update my saved answer'", async () => {
  render(<AgentRunHistory jobId={5} />);
  fireEvent.click(await waitFor(() => screen.getByRole("button", { name: /edit: why us/i })));
  const options = [...screen.getByLabelText(/where to save/i).options].map((o) => o.value);
  expect(options).toEqual(["once", "new"]);
});
