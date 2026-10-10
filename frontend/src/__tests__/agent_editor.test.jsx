import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { Editor } from "../agent/Editor.tsx";
import { treeItems } from "../agent/Overlays.tsx";

const noop = () => {};
const editor = (onSubmit = vi.fn()) => {
  render(<Editor commands={[]} running={false} onSubmit={onSubmit} onCommand={noop} onStop={noop} onTakeBack={noop}
    onCycleThinking={noop} onPickModel={noop} />);
  return { onSubmit, box: screen.getByLabelText("Message the agent") };
};
const png = () => new File([new Uint8Array([137, 80, 78, 71])], "shot.png", { type: "image/png" });

test("the box starts at one line", () => {
  expect(editor().box).toHaveAttribute("rows", "1");
});

test("a pasted picture is attached, shown, removable, and sent with the message", async () => {
  const { onSubmit, box } = editor();
  fireEvent.paste(box, { clipboardData: { items: [{ kind: "file", getAsFile: png }] } });
  expect(await screen.findByAltText("shot.png")).toBeInTheDocument();
  fireEvent.change(box, { target: { value: "what's wrong here?" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSubmit).toHaveBeenCalledWith("what's wrong here?", "steer", [expect.objectContaining({ mimeType: "image/png" })]);
  expect(screen.queryByAltText("shot.png")).toBeNull();
});

test("only pictures can be attached", async () => {
  editor();
  fireEvent.change(document.querySelector("input[type=file]"), { target: { files: [new File(["x"], "a.pdf", { type: "application/pdf" })] } });
  expect(await screen.findByText(/Only PNG, JPEG, WebP or GIF/)).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("list", { name: "Attached pictures" })).toBeNull());
});

test("/tree shows this conversation's messages with each branch under the message it split off after", () => {
  const sessions = [
    { id: "main", title: "Setting up", createdAt: 1 },
    { id: "aside", title: "About: clearance", createdAt: 3, parent: "main", forkAt: 12, aside: true },
    { id: "fork", title: "Fork of Setting up", createdAt: 2, parent: "main", forkAt: 4 },
  ];
  const labels = treeItems(sessions, "main", [{ id: 3, label: "first" }, { id: 10, label: "second" }]).map((i) => i.label.trim());
  expect(labels).toEqual(["Setting up", "› first", "⑂ Fork of Setting up", "› second", "⑂ aside: About: clearance"]);
  const inFork = treeItems(sessions, "fork", [{ id: 3, label: "first" }]).map((i) => i.label.trim());
  expect(inFork[0]).toBe("Setting up");                                         // where it came from, above
  expect(inFork[1]).toBe("Fork of Setting up");
});
