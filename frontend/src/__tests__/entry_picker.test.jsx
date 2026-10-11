import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { Thread } from "../agent/Thread.tsx";

vi.mock("../api.js", () => ({
  fetchQbankEntries: () => Promise.resolve([
    { id: "home_address", question: "What is your current residential address, including street, building and flat number?" },
    { id: "postal_code", question: "What is your postal code?" },
  ]),
}));
const { default: EntryPicker } = await import("../components/EntryPicker.jsx");

test("each match shows its whole question and picking one reports its id", async () => {
  const onChange = vi.fn();
  render(<EntryPicker id="p" label="Which question" onChange={onChange} />);
  const box = screen.getByLabelText("Which question");
  await waitFor(() => {
    fireEvent.change(box, { target: { value: "residential street" } });
    expect(screen.getByRole("option")).toHaveTextContent("including street, building and flat number?");
  });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onChange).toHaveBeenLastCalledWith("home_address");
  expect(box).toHaveAttribute("title", expect.stringContaining("flat number"));
});

test("retried model errors show once, with how many tries", () => {
  const err = (id) => ({ id, kind: "pi.assistant", model: [{ role: "assistant", content: [], errorMessage: "Request timed out." }] });
  render(<Thread entries={[{ id: 1, kind: "pi.user", model: [{ role: "user", content: "hi" }] }, err(2), err(3), err(4)]} />);
  expect(screen.getAllByText(/timed out/)).toHaveLength(1);
  expect(screen.getByText(/tried 3 times/)).toBeInTheDocument();
});
