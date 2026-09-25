import { render, screen } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import RetrievalPanel from "../components/RetrievalPanel.jsx";

const STATS = {
  total_fields: 40, retrieval_hits: 30, hit_rate: 0.75, by_tier: { label_exact: 12, fts_fuzzy: 14, semantic: 4 },
  by_source: {}, answered_by_memory: 24, retrieved_not_used: 6,
  reviewed: { kept: 5, edited: 3, wrong_rate: 0.375 },
  top_wrong_entries: [{ qkey: "years of java", edited: 3, kept: 0 }],
  generation: { by_status: {}, kept: { avg_confidence: 82, count: 4 }, edited: { avg_confidence: 44, count: 2 } },
};
const RECENT = [
  { id: 1, label: "Years of Python?", title: "ML Eng", company: "Acme", answer: "2", source: "learned", status: "filled",
    retrieval_kind: "fts_fuzzy", retrieved_qkey: "years of java", retrieval_score: 0.6, outcome: "edited",
    candidates_json: [{ tier: "learned", qkey: "years of java", score: 0.6, accepted: true },
                      { tier: "semantic", qkey: "experience", score: 0.9, accepted: false }] },
  { id: 2, label: "Favourite colour", title: "DS", company: "Globex", answer: null, source: null, status: "needs_answer",
    retrieval_kind: "none", retrieved_qkey: null, retrieval_score: null, outcome: null, candidates_json: [] },
];

function mock(stats) {
  global.fetch = vi.fn((url) => {
    const body = String(url).includes("/retrieval/stats") ? stats : { recent: RECENT };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
}

test("shows hit rate, memory-answered, wrong rate, tiers, worst entries and calibration", async () => {
  mock(STATS);
  render(<RetrievalPanel />);
  expect(await screen.findByTestId("stat-hit")).toHaveTextContent("75%");
  expect(screen.getByTestId("stat-used")).toHaveTextContent("24");
  expect(screen.getByTestId("stat-unused")).toHaveTextContent("6");
  expect(screen.getByTestId("stat-wrong")).toHaveTextContent("38%");
  expect(screen.getByText(/similar wording 14/)).toBeInTheDocument();
  expect(screen.getByText(/“years of java” — wrong 3×, right 0×/)).toBeInTheDocument();
  expect(screen.getByTestId("calibration")).toHaveTextContent("when right: 82 (4)");
  expect(screen.getByTestId("calibration")).toHaveTextContent("when wrong: 44 (2)");
});

test("recent list shows question -> retrieved entry (score) -> answer -> outcome, and rejected candidates", async () => {
  mock(STATS);
  render(<RetrievalPanel />);
  const row = await screen.findByTestId("recent-1");
  expect(row).toHaveTextContent("matched “years of java” (similar wording, score 0.6)");
  expect(row).toHaveTextContent("“2” (learned)");
  expect(row).toHaveTextContent("wrong");
  expect(row).toHaveTextContent("semantic: “experience” score 0.9 — rejected by the gate");
  expect(screen.getByTestId("recent-2")).toHaveTextContent("nothing retrieved → not filled");
});

test("empty database shows a hint instead of zeros", async () => {
  mock({ ...STATS, total_fields: 0 });
  render(<RetrievalPanel />);
  expect(await screen.findByText(/no runs recorded yet/)).toBeInTheDocument();
});
