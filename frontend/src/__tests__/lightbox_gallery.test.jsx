import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import ImageLightbox from "../components/ImageLightbox.jsx";

const shots = [1, 2, 3].map((n) => ({ src: `/s${n}.png`, alt: `Screenshot of page ${n}` }));

test("one viewer steps through a run's screenshots without closing", () => {
  render(<ImageLightbox src="/s2.png" alt="Screenshot of page 2" gallery={shots} index={1} />);
  fireEvent.click(screen.getByLabelText("Open Screenshot of page 2"));
  expect(screen.getByTestId("lightbox-count").textContent).toBe("2 / 3");
  fireEvent.click(screen.getByLabelText("Next screenshot"));
  expect(screen.getByRole("dialog").getAttribute("aria-label")).toBe("Screenshot of page 3");
  fireEvent.keyDown(window, { key: "ArrowRight" });            // wraps to the first
  expect(screen.getByTestId("lightbox-count").textContent).toBe("1 / 3");
  fireEvent.keyDown(window, { key: "ArrowLeft" });
  expect(screen.getByTestId("lightbox-count").textContent).toBe("3 / 3");
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("a single image shows no previous/next", () => {
  render(<ImageLightbox src="/one.png" alt="Live view" />);
  fireEvent.click(screen.getByLabelText("Open Live view"));
  expect(screen.queryByLabelText("Next screenshot")).toBeNull();
  expect(screen.queryByTestId("lightbox-count")).toBeNull();
});
