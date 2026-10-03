import { render, screen, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.mock("../api.js", () => ({
  startRefresh: vi.fn(() => Promise.resolve()),
  refreshStatus: vi.fn(() => Promise.resolve({
    running: false, stage: "done",
    last_result: { browser: [{ site: "linkedin", new: 12, note: "" }, { site: "naukri", new: 0, note: "blocked: authwall" }] },
  })),
}));
import RefreshButton from "../components/RefreshButton.jsx";

test("one compact browser chip with per-site detail on hover; only a block/error gets its own alert", async () => {
  render(<RefreshButton onDone={() => {}} />);
  fireEvent.click(screen.getByRole("button"));
  const chip = await screen.findByText("browser sources +12");
  expect(chip.getAttribute("role")).toBe("status");
  expect(chip.getAttribute("title")).toContain("linkedin +12");
  expect(chip.getAttribute("title")).toContain("naukri: blocked: authwall");
  expect(screen.getByText("naukri: blocked").getAttribute("role")).toBe("alert");
});

test("picks up a refresh already running when the page loads", async () => {
  const { refreshStatus } = await import("../api.js");
  refreshStatus.mockImplementationOnce(() => Promise.resolve({ running: true, stage: "browser sources", last_result: null }));
  render(<RefreshButton onDone={() => {}} />);
  const btn = await screen.findByText("browser sources");
  expect(btn.closest("button").disabled).toBe(true);
});
