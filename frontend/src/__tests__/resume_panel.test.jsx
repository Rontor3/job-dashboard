import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import ResumePanel from "../components/ResumePanel.jsx";

const SEGMENTS = [
  {
    id: "exp1",
    kind: "experience",
    title: "Senior Engineer @ Acme",
    tags: [],
    bullets: ["Built scalable systems", "Led a team of 5"],
  },
  {
    id: "skills1",
    kind: "skills",
    title: "Technical Skills",
    tags: [],
    bullets: ["Python, Go, Kubernetes"],
  },
  {
    id: "proj1",
    kind: "project",
    title: "Side Project",
    tags: [],
    bullets: ["Built a thing"],
  },
  {
    id: "edu1",
    kind: "education",
    title: "Education",
    tags: [],
    bullets: ["BS Computer Science"],
  },
];

const SUGGESTION = {
  block_ids: ["exp1", "skills1", "proj1"],
  rationale: "Strong match",
  rephrasings: [],
  gaps: [],
};

const ALTERNATIVES = {
  alternatives: [
    ["**Architected** scalable systems for 1M users"],
    ["Owned platform reliability across 3 teams"],
  ],
};

const GENERATED = {
  resume_id: "r-123",
  pdf_url: "https://example.com/resume.pdf",
  ats_report: {
    ats_score: 87,
    missing_keywords: ["k8s", "distributed-systems"],
  },
  blocks_used: ["exp1", "skills1", "proj1"],
  cut_lines: [],
  interview_prep: [],
};

beforeEach(() => {
  global.fetch = vi.fn((url, opts) => {
    if (String(url).includes("/resume/segments"))
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ segments: SEGMENTS }),
      });
    if (String(url).includes("/resume/regenerate-block"))
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(ALTERNATIVES),
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

async function openEditor() {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  // Title appears twice (block card + live preview), so use getAllByText.
  await waitFor(() =>
    expect(screen.getAllByText("Senior Engineer @ Acme").length).toBeGreaterThan(0)
  );
}

test("renders 'Tailor resume' button in idle state", () => {
  render(<ResumePanel jobId={1} />);
  expect(screen.getByText(/Tailor resume/)).toBeDefined();
});

test("shows loading message in suggesting stage (no JD scan)", () => {
  render(<ResumePanel jobId={1} />);
  fireEvent.click(screen.getByText(/Tailor resume/));
  expect(screen.getByText(/Loading your résumé/)).toBeDefined();
});

test("editor renders skills/experience/project blocks from mocked segments", async () => {
  await openEditor();
  expect(screen.getByText("Skills")).toBeDefined();
  expect(screen.getByText("Experience")).toBeDefined();
  expect(screen.getByText("Projects")).toBeDefined();
  // Titles appear twice each (block card + live preview).
  expect(screen.getAllByText("Senior Engineer @ Acme").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Technical Skills").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Side Project").length).toBeGreaterThan(0);
  // Non-editable kind (education) is not part of the block editor
  expect(screen.queryByText("Education")).toBeNull();
});

test("rewrite shows alternatives and keeps Original", async () => {
  await openEditor();
  // Render order follows kind grouping: Experience, Projects, Skills.
  const regenBtn = screen.getAllByText("Rewrite", { selector: "button" })[0];
  fireEvent.click(regenBtn);

  await waitFor(() => expect(screen.getByText("Alternative 1")).toBeDefined());
  expect(screen.getByText("Alternative 2")).toBeDefined();
  expect(screen.getByText("Original")).toBeDefined();

  // Picking an alternative updates the active bullets shown in the block
  fireEvent.click(screen.getByText("Alternative 1"));
  await waitFor(() =>
    expect(screen.getAllByText(/Architected/).length).toBeGreaterThan(0)
  );
});

test("edit updates the preview", async () => {
  await openEditor();
  // Render order follows kind grouping: Skills, Experience, Projects.
  const editButtons = screen.getAllByText("Edit", { selector: "button" });
  fireEvent.click(editButtons[1]); // Experience block's Edit

  const bulletsField = screen.getByLabelText("Block bullets");
  fireEvent.change(bulletsField, { target: { value: "A brand new bullet point" } });
  fireEvent.click(screen.getByText("Save", { selector: "button" }));

  await waitFor(() =>
    expect(screen.getAllByText(/A brand new bullet point/).length).toBeGreaterThan(0)
  );
  // Preview section reflects the update too
  expect(screen.getByText("Preview")).toBeDefined();
});

test("add creates a blank block in edit mode", async () => {
  await openEditor();
  fireEvent.click(screen.getByText("+ add project"));

  const titleField = screen.getByLabelText("Block title");
  expect(titleField.value).toBe("");
  fireEvent.change(titleField, { target: { value: "New Project" } });
  const bulletsField = screen.getByLabelText("Block bullets");
  fireEvent.change(bulletsField, { target: { value: "Shipped a new feature" } });
  fireEvent.click(screen.getByText("Save", { selector: "button" }));

  await waitFor(() =>
    expect(screen.getAllByText("New Project").length).toBeGreaterThan(0)
  );
  expect(screen.getAllByText(/Shipped a new feature/).length).toBeGreaterThan(0);
});

test("delete removes a block", async () => {
  await openEditor();
  // Render order follows kind grouping: Experience, Projects, Skills.
  const deleteButtons = screen.getAllByText("Delete", { selector: "button" });
  fireEvent.click(deleteButtons[0]); // deletes the Experience block

  await waitFor(() => expect(screen.queryByText("Senior Engineer @ Acme")).toBeNull());
});

test("generate POSTs a body containing layout", async () => {
  await openEditor();
  fireEvent.click(screen.getByText(/Generate tailored resume/));
  await waitFor(() => expect(screen.getByText(/Tailored draft ready/)).toBeDefined());

  const generateCall = global.fetch.mock.calls.find(([url]) =>
    String(url).includes("/resume/generate")
  );
  expect(generateCall).toBeDefined();
  const body = JSON.parse(generateCall[1].body);
  expect(body.layout).toBeDefined();
  expect(Array.isArray(body.layout)).toBe(true);
  expect(body.layout.length).toBe(3);
  // Untouched segment blocks generate as {segment_id}
  expect(body.layout).toContainEqual({ segment_id: "exp1" });
  expect(body.layout).toContainEqual({ segment_id: "skills1" });
  expect(body.layout).toContainEqual({ segment_id: "proj1" });
});

test("edited block sends kind/title/bullets in layout instead of segment_id", async () => {
  await openEditor();
  // Render order follows kind grouping: Experience, Projects, Skills.
  const editButtons = screen.getAllByText("Edit", { selector: "button" });
  fireEvent.click(editButtons[0]); // Experience
  fireEvent.change(screen.getByLabelText("Block bullets"), {
    target: { value: "Edited bullet one" },
  });
  fireEvent.click(screen.getByText("Save", { selector: "button" }));
  await waitFor(() => expect(screen.getAllByText(/Edited bullet one/).length).toBeGreaterThan(0));

  fireEvent.click(screen.getByText(/Generate tailored resume/));
  await waitFor(() => expect(screen.getByText(/Tailored draft ready/)).toBeDefined());

  const generateCall = global.fetch.mock.calls.find(([url]) =>
    String(url).includes("/resume/generate")
  );
  const body = JSON.parse(generateCall[1].body);
  expect(body.layout).toContainEqual({
    kind: "experience",
    title: "Senior Engineer @ Acme",
    bullets: ["Edited bullet one"],
  });
});

test("edited skills segment drops manifest title (label lives in bullets)", async () => {
  await openEditor();
  // Render order follows kind grouping: Experience, Projects, Skills.
  const editButtons = screen.getAllByText("Edit", { selector: "button" });
  fireEvent.click(editButtons[2]); // Skills
  fireEvent.change(screen.getByLabelText("Block bullets"), {
    target: { value: "**Python**, Go, Rust" },
  });
  fireEvent.click(screen.getByText("Save", { selector: "button" }));
  await waitFor(() => expect(screen.getAllByText(/Go, Rust/).length).toBeGreaterThan(0));

  fireEvent.click(screen.getByText(/Generate tailored resume/));
  await waitFor(() => expect(screen.getByText(/Tailored draft ready/)).toBeDefined());

  const generateCall = global.fetch.mock.calls.find(([url]) =>
    String(url).includes("/resume/generate")
  );
  const body = JSON.parse(generateCall[1].body);
  // title is "" so block_to_tex won't prepend the manifest heading a second
  // time on top of the **label** the bullets already carry.
  expect(body.layout).toContainEqual({
    kind: "skills",
    title: "",
    bullets: ["**Python**, Go, Rust"],
  });
});

test("after generate, renders pdf link", async () => {
  await openEditor();
  fireEvent.click(screen.getByText(/Generate tailored resume/));
  await waitFor(() => expect(screen.getByText(/Open PDF/)).toBeDefined());
  const link = screen.getByRole("link", { name: /Open PDF/ });
  expect(link.href).toBe(GENERATED.pdf_url);
});

test("after generate, renders ATS score and missing keywords", async () => {
  await openEditor();
  fireEvent.click(screen.getByText(/Generate tailored resume/));
  await waitFor(() => expect(screen.getByText(/ATS 87%/)).toBeDefined());
  expect(screen.getByText(/Tailored draft ready/)).toBeDefined();
  // Missing keywords render as one joined line above the editor.
  expect(screen.getByText(/k8s, distributed-systems/)).toBeDefined();
});

test("Cancel goes back to idle and clears the draft", async () => {
  await openEditor();
  fireEvent.click(screen.getByText(/Generate tailored resume/));
  await waitFor(() => expect(screen.getByText(/Tailored draft ready/)).toBeDefined());
  fireEvent.click(screen.getByText("Cancel", { selector: "button" }));
  await waitFor(() => expect(screen.queryByText(/Tailored draft ready/)).toBeNull());
  expect(screen.getByText(/Tailor resume/)).toBeDefined();
});
