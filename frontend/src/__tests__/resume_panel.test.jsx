import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import ResumePanel from "../components/ResumePanel.jsx";

const SEGMENTS = [
  { id: "exp", title: "Experience" },
  { id: "edu", title: "Education" },
  { id: "skills", title: "Skills" },
];

const SUGGESTION = {
  block_ids: ["exp", "skills"],
  rationale: "Strong match",
  rephrasings: [
    {
      original_text: "built ML models",
      proposed_text: "architected and deployed production ML systems",
      confidence: "equivalent",
    },
    {
      original_text: "Python",
      proposed_text: "Python 3.10+",
      confidence: "exact-synonym",
    },
  ],
  gaps: ["Kubernetes", "Docker"],
};

const GENERATED = {
  resume_id: "r-123",
  pdf_url: "https://example.com/resume.pdf",
  ats_report: {
    ats_score: 87,
    missing_keywords: ["k8s", "distributed-systems"],
  },
  blocks_used: ["exp", "skills"],
  cut_lines: [],
  interview_prep: [
    "Be ready to discuss ML model deployment at scale",
    "Emphasize experience with Python ecosystem",
  ],
};

beforeEach(() => {
  global.fetch = vi.fn((url, opts) => {
    if (String(url).includes("/resume/segments"))
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(SEGMENTS),
      });
    if (String(url).includes("/resume/suggest"))
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(SUGGESTION),
      });
    if (String(url).includes("/resume/generate"))
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(GENERATED),
      });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
});

test("renders 'Tailor resume' button in idle state", () => {
  render(<ResumePanel jobId={1} />);
  expect(screen.getByText(/Tailor resume/)).toBeDefined();
});

test("suggests resume and renders suggested blocks", async () => {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  await waitFor(() => expect(screen.getByText("Resume blocks")).toBeDefined());
  expect(screen.getByText("Experience")).toBeDefined();
  expect(screen.getByText("Skills")).toBeDefined();
});

test("suggested blocks are pre-checked", async () => {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  await waitFor(() => expect(screen.getByText("Resume blocks")).toBeDefined());
  const checkboxes = screen.getAllByRole("checkbox");
  // First checkbox is Experience (in suggested list)
  expect(checkboxes[0].checked).toBe(true);
  // Second checkbox is Skills (in suggested list)
  expect(checkboxes[1].checked).toBe(true);
  // Third checkbox would be for rephrasings, not in blocks
});

test("renders rephrasings with confidence tags", async () => {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  await waitFor(() =>
    expect(screen.getByText("Keyword suggestions")).toBeDefined()
  );
  expect(screen.getByText(/architected and deployed/)).toBeDefined();
  expect(screen.getByText("equivalent")).toBeDefined();
  expect(screen.getByText("exact-synonym")).toBeDefined();
});

test("renders gap chips with amber styling", async () => {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  await waitFor(() => expect(screen.getByText("Gaps")).toBeDefined());
  expect(screen.getByText(/Kubernetes/)).toBeDefined();
  expect(screen.getByText(/Docker/)).toBeDefined();
});

test("toggling blocks updates checkedBlocks", async () => {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  await waitFor(() => screen.getByText("Resume blocks"));
  const checkboxes = screen.getAllByRole("checkbox");
  const expCheckbox = checkboxes[0]; // Experience is first
  fireEvent.click(expCheckbox);
  expect(expCheckbox.checked).toBe(false);
  fireEvent.click(expCheckbox);
  expect(expCheckbox.checked).toBe(true);
});

test("generate calls generateResume with blockIds and acceptedRephrasings", async () => {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  await waitFor(() => screen.getByText("Resume blocks"));

  // Accept first rephrasing by clicking the first rephrasings checkbox (after block checkboxes)
  const allCheckboxes = screen.getAllByRole("checkbox");
  // allCheckboxes[0] and [1] are block checkboxes, [2] onwards are rephrasing checkboxes
  fireEvent.click(allCheckboxes[2]); // first rephrasing checkbox

  fireEvent.click(screen.getByText(/Generate tailored resume/));
  await waitFor(() => expect(screen.getByText(/ATS Score/)).toBeDefined());

  const generateCall = global.fetch.mock.calls.find(([url]) =>
    String(url).includes("/resume/generate")
  );
  expect(generateCall).toBeDefined();
  const body = JSON.parse(generateCall[1].body);
  expect(body.block_ids).toContain("exp");
  expect(body.block_ids).toContain("skills");
  expect(body.accepted_rephrasings).toBeDefined();
});

test("after generate, renders pdf link", async () => {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  await waitFor(() => screen.getByText("Resume blocks"));
  fireEvent.click(screen.getByText(/Generate tailored resume/));
  await waitFor(() => expect(screen.getByText(/Download tailored resume/)).toBeDefined());
  const link = screen.getByRole("link", { name: /Download tailored resume/ });
  expect(link.href).toBe(GENERATED.pdf_url);
});

test("after generate, renders ATS score", async () => {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  await waitFor(() => screen.getByText("Resume blocks"));
  fireEvent.click(screen.getByText(/Generate tailored resume/));
  await waitFor(() => expect(screen.getByText("87%")).toBeDefined());
  expect(screen.getByText(/ATS Score/)).toBeDefined();
});

test("after generate, renders missing keywords", async () => {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  await waitFor(() => screen.getByText("Resume blocks"));
  fireEvent.click(screen.getByText(/Generate tailored resume/));
  await waitFor(() => expect(screen.getByText("k8s")).toBeDefined());
  expect(screen.getByText("distributed-systems")).toBeDefined();
});

test("after generate, renders interview prep list", async () => {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  await waitFor(() => screen.getByText("Resume blocks"));
  fireEvent.click(screen.getByText(/Generate tailored resume/));
  await waitFor(() =>
    expect(
      screen.getByText(/Be ready to discuss ML model deployment/),
    ).toBeDefined()
  );
  expect(screen.getByText(/Emphasize experience with Python/)).toBeDefined();
});

test("Start over button goes back to idle", async () => {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  await waitFor(() => screen.getByText("Resume blocks"));
  fireEvent.click(screen.getByText(/Generate tailored resume/));
  await waitFor(() => expect(screen.getByText(/Start over/)).toBeDefined());
  fireEvent.click(screen.getByText(/Start over/));
  await waitFor(() => expect(screen.queryByText(/ATS Score/)).toBeNull());
  expect(screen.getByText(/Tailor resume/)).toBeDefined();
});
