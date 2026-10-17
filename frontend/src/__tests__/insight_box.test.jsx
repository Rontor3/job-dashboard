import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import InsightBox from "../components/InsightBox.jsx";
import RulesPanel from "../components/RulesPanel.jsx";

let calls;
const REWRITE = { answer: "No", before: "Yes", origin: "similar", trace: ["fact plan: agree"],
  directive: { lever: "derive", why: "the job is in another city" },
  proposal: { lever: "derive", label: "Are you based in Ahmedabad?", concept: "living in the job's city",
              rule: "When asked if I live in the job's city, compare it with mine", applies_to: "similar", kind: "radio_group" } };
beforeEach(() => {
  calls = [];
  global.fetch = vi.fn((url, opts = {}) => {
    const u = String(url);
    calls.push([u, opts.method || "GET", opts.body && JSON.parse(opts.body)]);
    const body = u.endsWith("/rewrite") ? REWRITE
      : u.endsWith("/api/lessons/reach") ? { count: 2, rows: 3, examples: [{ label: "Are you based in Pune?", seen: 2 }] }
      : u.endsWith("/api/lessons") && opts.method === "POST" ? { lesson_id: 7, filed_in: "rule" }
      : u.endsWith("/api/lessons") ? { lessons: [
          { id: 7, lever: "derive", applies_to: "similar", status: "active", hits: 3, rule: "compare the job's city with mine",
            why: "the job is elsewhere", notes: ["use the JD location"], created_at: "2026-10-17T00:00:00Z", filed_in: "rule" },
          { id: 6, lever: "fact", applies_to: "question", status: "filed", hits: 0, rule: null, concept: "current CTC",
            before: { entry: "current_ctc", answer: "22" }, notes: [], created_at: "2026-10-17T00:00:00Z", filed_in: "answer current_ctc" }] }
      : { ok: true };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("a note becomes a cause, a rewritten answer and a rule you can scope, then both are saved", async () => {
  const q = { id: 11, label: "Are you based in Ahmedabad?", kind: "radio_group" };
  render(<InsightBox q={q} jobId={3} />);
  fireEvent.click(screen.getByRole("button", { name: /Tell it what's wrong/ }));
  fireEvent.change(screen.getByLabelText("What's wrong"), { target: { value: "compare the JD location with mine" } });
  fireEvent.click(screen.getByRole("button", { name: "Rewrite" }));
  expect(await screen.findByText(/has to be worked out/)).toBeInTheDocument();
  expect(screen.getByLabelText("New answer")).toHaveValue("No");
  expect(await screen.findByText("Where should this apply?")).toBeInTheDocument();
  expect(within(screen.getByRole("radio", { name: /Questions about the same thing/ })).getByText("suggested")).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: /Questions about the same thing/ })).toHaveAttribute("aria-checked", "true");
  await waitFor(() => expect(screen.getAllByText("2 past")).toHaveLength(4));
  expect(calls.find(([u]) => u.endsWith("/rewrite"))[2]).toEqual({ notes: ["compare the JD location with mine"] });
  fireEvent.click(screen.getByRole("radio", { name: /Only this question/ }));
  expect(screen.getByRole("radio", { name: /Only this question/ })).toHaveAttribute("aria-checked", "true");
  fireEvent.keyDown(screen.getByRole("radiogroup", { name: "Applies to" }), { key: "4" });
  expect(screen.getByRole("radio", { name: /Every short field/ })).toHaveAttribute("aria-checked", "true");
  fireEvent.keyDown(screen.getByRole("radiogroup", { name: "Applies to" }), { key: "1" });
  fireEvent.click(screen.getByRole("button", { name: "Accept" }));
  expect(await screen.findByText(/Learned: rule/)).toBeInTheDocument();
  expect(calls.some(([u, m, b]) => u === "/api/application-qa/11/answer" && m === "PUT" && b.answer === "No")).toBe(true);
  const filed = calls.find(([u, m]) => u === "/api/lessons" && m === "POST")[2];
  expect(filed.proposal.applies_to).toBe("question");
});

test("try again sends every note so far", async () => {
  render(<InsightBox q={{ id: 11, label: "Q" }} />);
  fireEvent.click(screen.getByRole("button", { name: /Tell it what's wrong/ }));
  fireEvent.change(screen.getByLabelText("What's wrong"), { target: { value: "first" } });
  fireEvent.click(screen.getByRole("button", { name: "Rewrite" }));
  await screen.findByLabelText("New answer");
  fireEvent.change(screen.getByLabelText("What's wrong"), { target: { value: "second" } });
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await waitFor(() => expect(calls.filter(([u]) => u.endsWith("/rewrite")).pop()[2].notes).toEqual(["first", "second"]));
});

test("Memory → Rules lists rules apart from filed facts, and a rule can be turned off", async () => {
  render(<RulesPanel />);
  expect(await screen.findByText("compare the job's city with mine")).toBeInTheDocument();
  expect(screen.getByText(/replaced “22”/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Turn off" }));
  await waitFor(() => expect(calls.some(([u, m, b]) => u === "/api/lessons/7" && m === "PUT" && b.status === "off")).toBe(true));
});
