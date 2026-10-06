import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ImageLightbox from "../components/ImageLightbox.jsx";

const mount = () => render(<ImageLightbox src="/shot.png" alt="Screenshot of page 1" />);
const open = () => fireEvent.click(screen.getByRole("button", { name: /open screenshot of page 1/i }));

describe("ImageLightbox", () => {
  it("opens the image with a visible Close that dismisses it", () => {
    mount(); open();
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /close image/i }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("closes on Escape and on a backdrop click, but not when the image itself is clicked", () => {
    mount(); open();
    fireEvent.click(screen.getAllByAltText("Screenshot of page 1").pop());
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    open();
    fireEvent.click(screen.getByRole("dialog"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
