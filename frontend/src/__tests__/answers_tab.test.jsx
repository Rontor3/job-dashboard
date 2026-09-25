import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import AnswersTab from "../components/AnswersTab.jsx";

const ANSWERS = [
  { qkey: "notice period", question: "Notice period?", answer: "30 days", purpose: null, updated_at: "2026-09-01",
    in_learned: true, in_vault: true, confidence: 1.0, approved_count: 3, autonomous: true, asked_in: 2 },
  { qkey: "why us", question: "Why us?", answer: "fraud ML", purpose: null, updated_at: null,
    in_learned: false, in_vault: true, confidence: 0.33, approved_count: 1, autonomous: false, asked_in: 0 },
];

function mock() {
  const calls = [];
  global.fetch = vi.fn((url, opts) => {
    const u = String(url);
    calls.push([u, opts]);
    const ok = (b) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(b) });
    if (u.includes("/api/agent-settings")) return ok({ answer_confidence_min: 60 });
    if (u.includes("/api/ingredients")) return ok({ units: [{ id: "u1", title: "Fraud pipeline", org: "Tata AIG", type: "project" }], skills_pool: [] });
    if (u.includes("/api/answers/applications")) return ok({ applications: [{ job_id: 1, title: "ML Eng", company: "Acme" }] });
    if (u.includes("/api/answers")) return ok(opts && opts.method ? { ok: true } : { answers: ANSWERS });
    return ok({});
  });
  return calls;
}

beforeEach(() => { vi.restoreAllMocks(); });

test("lists answers with trust state and asked-in count; ingredients are read-only", async () => {
  mock();
  render(<AnswersTab />);
  expect(await screen.findByText("Notice period?")).toBeInTheDocument();
  expect(screen.getByText("autonomous")).toBeInTheDocument();
  expect(screen.getByText("1/3 approvals")).toBeInTheDocument();
  expect(screen.getByText("asked in 2 applications")).toBeInTheDocument();
  expect(screen.getByText("not asked yet")).toBeInTheDocument();
  expect(await screen.findByText(/Ingredients \(1\) — read-only/)).toBeInTheDocument();
});

test("editing saves through PUT with the question and new answer", async () => {
  const calls = mock();
  render(<AnswersTab />);
  await screen.findByText("Notice period?");
  fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
  fireEvent.change(screen.getByLabelText("Edit answer"), { target: { value: "60 days" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => {
    const put = calls.find(([, o]) => o && o.method === "PUT" && !String(o.body).includes("answer_confidence_min"));
    expect(JSON.parse(put[1].body)).toMatchObject({ question: "Notice period?", answer: "60 days" });
  });
});

test("delete asks for confirmation, then calls DELETE with the qkey", async () => {
  const calls = mock();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<AnswersTab />);
  await screen.findByText("Notice period?");
  fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
  await waitFor(() => expect(calls.some(([u, o]) => o && o.method === "DELETE" && u.includes("qkey=notice%20period"))).toBe(true));
});

test("threshold saves via agent-settings", async () => {
  const calls = mock();
  render(<AnswersTab />);
  const box = await screen.findByLabelText(/Minimum confidence/);
  fireEvent.change(box, { target: { value: "75" } });
  fireEvent.click(screen.getByRole("button", { name: "Save threshold" }));
  await waitFor(() => {
    const put = calls.find(([u, o]) => u.includes("/api/agent-settings") && o && o.method === "PUT");
    expect(JSON.parse(put[1].body)).toEqual({ answer_confidence_min: 75 });
  });
});
