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

test("shows per-site browser results; blocked note is an alert", async () => {
  render(<RefreshButton onDone={() => {}} />);
  fireEvent.click(screen.getByRole("button"));
  expect((await screen.findByText("linkedin +12")).getAttribute("role")).toBe("status");
  expect(screen.getByText("naukri: blocked: authwall").getAttribute("role")).toBe("alert");
});
