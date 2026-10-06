import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import IngredientsPanel from "../components/IngredientsPanel.jsx";

const UNIT = { id: "u1", type: "project", title: "Fraud", org: "Tata", problem: "slow", approach: "ML", tech: ["ML", "AWS"],
               impact: ["ROC > 0.85"], tags: ["fraud"], source: "verbatim text" };

function mock() {
  const calls = [];
  global.fetch = vi.fn((url, opts) => {
    calls.push([String(url), opts]);
    const body = opts && opts.method === "PUT" ? { ...UNIT, ...JSON.parse(opts.body) } : { units: [UNIT], skills_pool: [] };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  return calls;
}

test("edits a unit and keeps the verbatim source locked until unlocked", async () => {
  const calls = mock();
  render(<IngredientsPanel />);
  fireEvent.change(await screen.findByLabelText("Problem of Fraud"), { target: { value: "manual review was slow" } });
  fireEvent.change(screen.getByLabelText("Tech (comma separated) of Fraud"), { target: { value: "ML, AWS, Spark" } });
  expect(screen.getByLabelText("Source of Fraud")).toHaveAttribute("readonly");
  fireEvent.click(screen.getByRole("button", { name: "Save Fraud" }));
  await waitFor(() => {
    const put = calls.find(([, o]) => o && o.method === "PUT");
    const b = JSON.parse(put[1].body);
    expect(b.problem).toBe("manual review was slow");
    expect(b.tech).toEqual(["ML", "AWS", "Spark"]);
    expect(b.source).toBeUndefined();
  });
});

test("an unlocked, changed source is sent with confirm_source", async () => {
  const calls = mock();
  render(<IngredientsPanel />);
  await screen.findByLabelText("Source of Fraud");
  fireEvent.click(screen.getByRole("button", { name: "Unlock source of Fraud" }));
  fireEvent.change(screen.getByLabelText("Source of Fraud"), { target: { value: "new verbatim" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Fraud" }));
  await waitFor(() => {
    const b = JSON.parse(calls.find(([, o]) => o && o.method === "PUT")[1].body);
    expect(b.source).toBe("new verbatim");
    expect(b.confirm_source).toBe(true);
  });
});
