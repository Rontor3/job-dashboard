import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import CoverLetterPanel from "../components/CoverLetterPanel.jsx";

const DRAFT = {
  body: "Dear Hiring Manager,\n\nI am excited about this opportunity.\n\nSincerely,\nCandidate",
  company_facts_used: [
    { text: "Acme Corp raised a Series B in 2023.", source_url: "https://example.com/acme-news" },
  ],
  flags: [],
  grounding: {
    unsupported_company_claims: ["Acme is the fastest-growing startup in its space"],
  },
};

const DRAFT_NO_FACTS = {
  body: "Dear Hiring Manager,\n\nGeneral letter body.\n\nSincerely,\nCandidate",
  company_facts_used: [],
  flags: [],
  grounding: { unsupported_company_claims: [] },
};

const GENERATED = {
  cover_letter_id: "cl-123",
  pdf_url: "https://example.com/cover-letter.pdf",
};

function mockFetch(draftResponse) {
  return vi.fn((url, opts) => {
    if (String(url).includes("/cover-letter/draft"))
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(draftResponse),
      });
    if (String(url).includes("/cover-letter/generate"))
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(GENERATED),
      });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
}

beforeEach(() => {
  global.fetch = mockFetch(DRAFT);
});

test("renders 'Draft cover letter' button in idle state", () => {
  render(<CoverLetterPanel jobId={1} />);
  expect(screen.getByText(/Draft cover letter/)).toBeDefined();
});

test("after draft: cited facts render with source_url link, body textarea populated, amber flag chip renders", async () => {
  render(<CoverLetterPanel jobId={1} />);
  fireEvent.click(screen.getByText(/Draft cover letter/));
  await waitFor(() => expect(screen.getByText("Company research used")).toBeDefined());

  expect(screen.getByText(/Acme Corp raised a Series B/)).toBeDefined();
  const link = screen.getByRole("link", { name: /source/ });
  expect(link.href).toBe(DRAFT.company_facts_used[0].source_url);
  expect(link.getAttribute("rel")).toContain("noopener");

  const textarea = screen.getByRole("textbox");
  expect(textarea.value).toBe(DRAFT.body);

  expect(screen.getByText(/Verify: Acme is the fastest-growing startup/)).toBeDefined();
});

test("editing body then Generate calls generate with the EDITED text", async () => {
  render(<CoverLetterPanel jobId={1} />);
  fireEvent.click(screen.getByText(/Draft cover letter/));
  await waitFor(() => screen.getByText("Company research used"));

  const textarea = screen.getByRole("textbox");
  fireEvent.change(textarea, { target: { value: "EDITED LETTER BODY" } });

  fireEvent.click(screen.getByText(/Generate PDF/));
  await waitFor(() => expect(screen.getByText(/Download cover letter/)).toBeDefined());

  const generateCall = global.fetch.mock.calls.find(([url]) =>
    String(url).includes("/cover-letter/generate")
  );
  expect(generateCall).toBeDefined();
  const body = JSON.parse(generateCall[1].body);
  expect(body.body).toBe("EDITED LETTER BODY");
  expect(body.body).not.toBe(DRAFT.body);
});

test("pdf link renders after generate", async () => {
  render(<CoverLetterPanel jobId={1} />);
  fireEvent.click(screen.getByText(/Draft cover letter/));
  await waitFor(() => screen.getByText("Company research used"));
  fireEvent.click(screen.getByText(/Generate PDF/));
  await waitFor(() => expect(screen.getByText(/Download cover letter/)).toBeDefined());
  const link = screen.getByRole("link", { name: /Download cover letter/ });
  expect(link.href).toBe(GENERATED.pdf_url);
});

test("no send/apply/email control anywhere", async () => {
  render(<CoverLetterPanel jobId={1} />);
  expect(screen.queryByText(/send/i)).toBeNull();
  expect(screen.queryByText(/email/i)).toBeNull();
  expect(screen.queryByText(/apply/i)).toBeNull();

  fireEvent.click(screen.getByText(/Draft cover letter/));
  await waitFor(() => screen.getByText("Company research used"));
  expect(screen.queryByText(/send/i)).toBeNull();
  expect(screen.queryByText(/email/i)).toBeNull();
  expect(screen.queryByText(/apply/i)).toBeNull();

  fireEvent.click(screen.getByText(/Generate PDF/));
  await waitFor(() => screen.getByText(/Download cover letter/));
  expect(screen.queryByText(/send/i)).toBeNull();
  expect(screen.queryByText(/email/i)).toBeNull();
  expect(screen.queryByText(/apply/i)).toBeNull();
});

test("empty company_facts_used renders muted general note", async () => {
  global.fetch = mockFetch(DRAFT_NO_FACTS);
  render(<CoverLetterPanel jobId={1} />);
  fireEvent.click(screen.getByText(/Draft cover letter/));
  await waitFor(() =>
    expect(
      screen.getByText(/No company-specific research found — letter kept general\./)
    ).toBeDefined()
  );
});
