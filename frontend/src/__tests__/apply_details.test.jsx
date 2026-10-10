import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import ApplyDetails from "../components/ApplyDetails.jsx";

let calls;
beforeEach(() => {
  calls = [];
  global.fetch = vi.fn((url, opts = {}) => {
    calls.push([String(url), opts.method || "GET", opts.body && JSON.parse(opts.body)]);
    const body = (opts.method || "GET") === "GET" ? { id: 7, apply_details: { worked_before: true } } : { ok: true };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("saves this job's referrer and flags, then applies", async () => {
  const apply = vi.fn();
  render(<ApplyDetails jobId={7} onApply={apply} />);
  expect(await screen.findByRole("button", { name: "Worked here before" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.change(screen.getByLabelText("Referred by"), { target: { value: "Jane Doe" } });
  fireEvent.click(screen.getByRole("button", { name: "Relative or close friend works here" }));
  fireEvent.click(screen.getByRole("button", { name: "Save & apply" }));
  await waitFor(() => expect(apply).toHaveBeenCalledWith(7));
  const put = calls.find(([, m]) => m === "PUT");
  expect(put[0]).toBe("/api/jobs/7/apply-details");
  expect(put[2]).toEqual({ referrer: "Jane Doe", relatives: true, applied_before: false, interviewed_before: false, worked_before: true });
});
