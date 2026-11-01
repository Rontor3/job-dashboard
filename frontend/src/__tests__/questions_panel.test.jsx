import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import QuestionsPanel from "../components/QuestionsPanel.jsx";

// A choice question shows its options (Lingaro 'Choose your salary period' was a bare text box), the agent's pick
// preselected even when its case differs; a free-text question keeps its text box.
let posted;
beforeEach(() => {
  posted = null;
  global.fetch = vi.fn((url, opts = {}) => {
    if (opts.method === "POST") posted = JSON.parse(opts.body);
    const body = String(url).endsWith("/questions") ? { questions: [
      { id: 1, label: "Choose your salary period*", kind: "select", answer: "annual", options_json: ["Month", "Hour", "Annual", "Day"] },
      { id: 2, label: "When can you start?", kind: "text", answer: "", options_json: null },
      { id: 3, label: "Current annual compensation in INR?", kind: "text", answer: "2500000", source: "qbank_likely",
        retrieved_qkey: "current_ctc", options_json: null }] } : { ok: true };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("choice questions show their options and save the one picked", async () => {
  render(<QuestionsPanel jobId={5} />);
  const annual = await screen.findByLabelText("Annual");
  expect(annual.checked).toBe(true);
  expect(screen.getByLabelText("Answer for When can you start?").tagName).toBe("TEXTAREA");
  fireEvent.click(screen.getByLabelText("Month"));
  fireEvent.click(screen.getAllByText("Save answer")[0]);
  await waitFor(() => expect(posted && posted.answer).toBe("Month"));
});


test("a guess matched to a saved answer is confirmed as another wording of it", async () => {
  render(<QuestionsPanel jobId={5} />);
  await screen.findByText(/link this wording to your saved answer “current_ctc”/);
  fireEvent.click(screen.getByText("Confirm"));
  await waitFor(() => expect(posted).toEqual({ answer: "2500000", save_as: "wording", entry_id: "current_ctc" }));
});
