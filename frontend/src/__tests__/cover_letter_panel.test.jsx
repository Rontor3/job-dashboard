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

const RESOURCES = {
  company: "Acme",
  resources: [
    {
      source_url: "https://acme.com/acs",
      title: "acme.com",
      summary: "Account Confidence Score, an AI/ML fraud score.",
      selected: false,
    },
    {
      source_url: "https://blog.acme.com/mesh",
      title: "blog.acme.com",
      summary: "Built a data mesh.",
      selected: false,
    },
  ],
};

const RESOURCES_3 = {
  company: "Acme",
  resources: [
    { source_url: "https://a.com/1", title: "a.com", summary: "Fact one.", selected: false },
    { source_url: "https://a.com/2", title: "a.com", summary: "Fact two.", selected: false },
    { source_url: "https://a.com/3", title: "a.com", summary: "Fact three.", selected: false },
  ],
};

test("gathers and renders company resource cards with source links", async () => {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/company-research"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(RESOURCES) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resources: [] }) });
  });
  render(<CoverLetterPanel jobId={1} />);
  fireEvent.click(screen.getByText(/Find company research/));
  await waitFor(() => expect(screen.getByText(/Account Confidence Score/)).toBeDefined());
  const link = screen.getByRole("link", { name: "acme.com" });
  expect(link.href).toContain("acme.com/acs");
  expect(link.target).toBe("_blank");
  expect(link.getAttribute("rel")).toContain("noopener");
});

test("selecting more than two sources is prevented", async () => {
  global.fetch = vi.fn((url, opts) => {
    if (String(url).includes("/company-research"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(RESOURCES_3) });
    if (String(url).includes("/company-resources/select"))
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ resources: RESOURCES_3.resources }),
      });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resources: [] }) });
  });
  render(<CoverLetterPanel jobId={1} />);
  fireEvent.click(screen.getByText(/Find company research/));
  await waitFor(() => expect(screen.getByText(/Fact one/)).toBeDefined());

  const checkboxes = screen.getAllByRole("checkbox");
  expect(checkboxes.length).toBe(3);
  fireEvent.click(checkboxes[0]);
  fireEvent.click(checkboxes[1]);
  fireEvent.click(checkboxes[2]);

  await waitFor(() =>
    expect(screen.getByText(/pick up to 2/i)).toBeDefined()
  );

  const selectCalls = global.fetch.mock.calls.filter(([url]) =>
    String(url).includes("/company-resources/select")
  );
  expect(selectCalls.length).toBeGreaterThan(0);
  selectCalls.forEach(([, opts]) => {
    const body = JSON.parse(opts.body);
    expect(body.source_urls.length).toBeLessThanOrEqual(2);
  });

  // the 3rd checkbox never got checked
  expect(checkboxes[0].checked).toBe(true);
  expect(checkboxes[1].checked).toBe(true);
  expect(checkboxes[2].checked).toBe(false);
});

test("saved company resources auto-load on mount without clicking Find company research", async () => {
  const SAVED = {
    company: "Acme",
    resources: [
      {
        source_url: "https://acme.com/acs",
        title: "acme.com",
        summary: "Account Confidence Score, an AI/ML fraud score.",
        selected: true,
      },
      {
        source_url: "https://blog.acme.com/mesh",
        title: "blog.acme.com",
        summary: "Built a data mesh.",
        selected: false,
      },
    ],
  };
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/company-resources"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(SAVED) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
  render(<CoverLetterPanel jobId={1} />);

  await waitFor(() => expect(screen.getByText(/Account Confidence Score/)).toBeDefined());
  expect(screen.getByText(/Built a data mesh/)).toBeDefined();

  const checkboxes = screen.getAllByRole("checkbox");
  expect(checkboxes.length).toBe(2);
  expect(checkboxes[0].checked).toBe(true);
  expect(checkboxes[1].checked).toBe(false);
});

test("no send/apply/email control exists in the research step", async () => {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(RESOURCES) })
  );
  render(<CoverLetterPanel jobId={1} />);
  fireEvent.click(screen.getByText(/Find company research/));
  await waitFor(() => screen.getByText(/data mesh/));
  expect(screen.queryByText(/send/i)).toBeNull();
  expect(screen.queryByText(/apply/i)).toBeNull();
  expect(screen.queryByText(/email/i)).toBeNull();
});
