import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import AboutMe, { withoutFact } from "../components/AboutMe.jsx";

const TEXT = "# About me\n\n## Target\n- Staff ML infra roles\n- Bangalore or remote\n\n## Constraints\n- No crypto\n";
const ABOUT = {
  exists: true, text: TEXT, known_sections: ["Target", "Preferences", "Constraints", "Background", "Working style", "Other"],
  sections: { Target: ["Staff ML infra roles", "Bangalore or remote"], Constraints: ["No crypto"] },
};
let calls;
beforeEach(() => {
  calls = [];
  global.fetch = vi.fn((url, opts = {}) => {
    calls.push([String(url), opts.method || "GET", opts.body && JSON.parse(opts.body)]);
    const body = String(url).includes("/api/changes") ? { changes: [
      { id: 9, at: new Date().toISOString(), actor: "agent", entity: "file", entity_id: "about_me", field: "text",
        before: null, after: null, undoable: true, undone_at: null, undo_of: null }] } : ABOUT;
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("shows what the agents learned by section, and what they saved lately with Undo", async () => {
  render(<AboutMe />);
  expect(await screen.findByText("Staff ML infra roles")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Constraints" })).toHaveTextContent("No crypto");
  expect(screen.getByText(/3 things the agents know about you/)).toBeInTheDocument();
  expect(await screen.findByText("Updated what the agent knows about you")).toBeInTheDocument();
});

test("add, reword and remove facts", async () => {
  render(<AboutMe />);
  await screen.findByText("No crypto");
  fireEvent.change(screen.getByLabelText("Add to Preferences"), { target: { value: "Small teams" } });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));
  await waitFor(() => expect(calls.some(([u, m, b]) => u.endsWith("/api/about-me/facts") && m === "POST"
    && b.section === "Preferences" && b.fact === "Small teams")).toBe(true));

  fireEvent.click(screen.getByRole("button", { name: "Edit No crypto" }));
  fireEvent.change(screen.getByLabelText("Reword No crypto"), { target: { value: "No crypto or gambling" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.some(([, , b]) => b?.replaces === "No crypto" && b.fact === "No crypto or gambling")).toBe(true));

  fireEvent.click(screen.getByRole("button", { name: "Remove Bangalore or remote" }));
  await waitFor(() => expect(calls.some(([u, m, b]) => u.endsWith("/api/about-me") && m === "PUT"
    && !b.text.includes("Bangalore") && b.text.includes("Staff ML infra roles"))).toBe(true));
});

test("withoutFact drops exactly one bullet", () => {
  expect(withoutFact(TEXT, "No crypto")).not.toContain("No crypto");
  expect(withoutFact(TEXT, "nothing")).toBe(TEXT);
});
