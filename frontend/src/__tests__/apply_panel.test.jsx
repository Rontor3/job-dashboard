import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import ApplyPanel from "../components/ApplyPanel.jsx";

const PACKAGE_WITH_LETTER = {
  profile: {
    full_name: "Jamie Rivera", email: "jamie@example.com", phone: null,
    location: null, linkedin_url: null, github_url: null, portfolio_url: null,
    work_authorization: null, years_experience: null,
    willing_to_relocate: null, notice_period: null, salary_expectation: null,
    updated_at: "2026-07-01T00:00:00+00:00",
  },
  resume: {
    id: 1, job_id: 1, pdf_path: "/data/resumes/1/jamie-resume.pdf",
    blocks_used: [], ats_score: 0.8, ats_report: {}, created_at: "2026-07-01T00:00:00+00:00",
  },
  cover_letter: {
    id: 7, job_id: 1, pdf_path: "/data/cover_letters/1/cl.pdf",
    body: "Dear hiring manager...", company_facts_used: [], created_at: "2026-07-01T00:00:00+00:00",
  },
  job: { id: 1, title: "ML Engineer", company: "Acme", job_url: "https://example.com/job/1" },
  ats_hint: "greenhouse",
};

const PACKAGE_NO_LETTER = {
  profile: { ...PACKAGE_WITH_LETTER.profile },
  resume: { ...PACKAGE_WITH_LETTER.resume },
  cover_letter: null,
  job: { id: 1, title: "ML Engineer", company: "Acme", job_url: "https://example.com/job/1" },
  ats_hint: "greenhouse",
};

const PACKAGE_NO_PROFILE = {
  profile: {},
  resume: { ...PACKAGE_WITH_LETTER.resume },
  cover_letter: null,
  job: { id: 1, title: "ML Engineer", company: "Acme", job_url: "https://example.com/job/1" },
  ats_hint: null,
};

function mockFetch({ pkg = PACKAGE_WITH_LETTER, application = {}, onSave } = {}) {
  return vi.fn((url, opts) => {
    const u = String(url);
    if (u.includes("/application-package"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(pkg) });
    if (u.endsWith("/application") && (!opts || opts.method === undefined))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(application) });
    if (u.endsWith("/application") && opts && opts.method === "POST") {
      if (onSave) onSave(JSON.parse(opts.body));
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ application_id: "app-1", status: JSON.parse(opts.body).status }),
      });
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
}

beforeEach(() => {
  global.fetch = mockFetch();
});

test("renders package: profile full_name, resume shown, cover-letter toggle present but off by default", async () => {
  render(<ApplyPanel jobId={1} />);
  await waitFor(() => expect(screen.getByText(/jamie-resume\.pdf/)).toBeDefined());
  expect(screen.getByText(/Jamie Rivera/)).toBeDefined();
  const checkbox = screen.getByRole("checkbox");
  expect(checkbox.checked).toBe(false);
});

test("cover-letter toggle is hidden when package.cover_letter is null", async () => {
  global.fetch = mockFetch({ pkg: PACKAGE_NO_LETTER });
  render(<ApplyPanel jobId={1} />);
  await waitFor(() => expect(screen.getByText(/jamie-resume\.pdf/)).toBeDefined());
  expect(screen.queryByRole("checkbox")).toBeNull();
});

test("shows 'set up your application profile' note when profile is empty", async () => {
  global.fetch = mockFetch({ pkg: PACKAGE_NO_PROFILE });
  render(<ApplyPanel jobId={1} />);
  await waitFor(() =>
    expect(screen.getByText(/set up your application profile/i)).toBeDefined()
  );
});

test("safety banner text is present", async () => {
  render(<ApplyPanel jobId={1} />);
  await waitFor(() => expect(screen.getByText(/jamie-resume\.pdf/)).toBeDefined());
  expect(
    screen.getByText(
      /The agent fills the form in your Chrome and stops at Submit — you review and send it\. It never submits, logs in, or solves CAPTCHAs\./
    )
  ).toBeDefined();
});

test("Prepare application calls saveApplication with status 'prepared'", async () => {
  const onSave = vi.fn();
  global.fetch = mockFetch({ onSave });
  render(<ApplyPanel jobId={1} />);
  await waitFor(() => screen.getByText(/Prepare application/));
  fireEvent.click(screen.getByText(/Prepare application/));
  await waitFor(() => expect(screen.getByText(/Mark as applied/)).toBeDefined());
  expect(onSave).toHaveBeenCalledWith(
    expect.objectContaining({ status: "prepared", cover_letter_id: null, ats: "greenhouse" })
  );
});

test("toggling cover letter on then Prepare sends the cover_letter_id", async () => {
  const onSave = vi.fn();
  global.fetch = mockFetch({ onSave });
  render(<ApplyPanel jobId={1} />);
  await waitFor(() => screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByText(/Prepare application/));
  await waitFor(() => expect(screen.getByText(/Mark as applied/)).toBeDefined());
  expect(onSave).toHaveBeenCalledWith(
    expect.objectContaining({ status: "prepared", cover_letter_id: 7 })
  );
});

test("Mark as applied calls saveApplication with status 'applied'", async () => {
  const onSave = vi.fn();
  global.fetch = mockFetch({ onSave });
  render(<ApplyPanel jobId={1} />);
  await waitFor(() => screen.getByText(/Prepare application/));
  fireEvent.click(screen.getByText(/Prepare application/));
  await waitFor(() => screen.getByText(/Mark as applied/));
  fireEvent.click(screen.getByText(/Mark as applied/));
  await waitFor(() => expect(screen.getByText(/Marked as applied/)).toBeDefined());
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ status: "applied" }));
});

test("no submit/auto-apply/log-in control exists as a clickable button anywhere in the flow", async () => {
  render(<ApplyPanel jobId={1} />);
  await waitFor(() => screen.getByText(/Prepare application/));
  let buttons = screen.queryAllByRole("button");
  buttons.forEach((b) => {
    expect(b.textContent).not.toMatch(/submit/i);
    expect(b.textContent).not.toMatch(/auto.?apply/i);
    expect(b.textContent).not.toMatch(/log ?in/i);
  });

  fireEvent.click(screen.getByText(/Prepare application/));
  await waitFor(() => screen.getByText(/Mark as applied/));
  buttons = screen.queryAllByRole("button");
  buttons.forEach((b) => {
    expect(b.textContent).not.toMatch(/submit/i);
    expect(b.textContent).not.toMatch(/auto.?apply/i);
    expect(b.textContent).not.toMatch(/log ?in/i);
  });

  fireEvent.click(screen.getByText(/Mark as applied/));
  await waitFor(() => screen.getByText(/Marked as applied/));
  buttons = screen.queryAllByRole("button");
  buttons.forEach((b) => {
    expect(b.textContent).not.toMatch(/submit/i);
    expect(b.textContent).not.toMatch(/auto.?apply/i);
    expect(b.textContent).not.toMatch(/log ?in/i);
  });
  // banner mentions these words in copy, but no button does
  expect(screen.getByText(/stops at Submit/)).toBeDefined();
});
