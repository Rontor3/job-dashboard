import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import ThemeToggle from "../components/ThemeToggle.jsx";

afterEach(() => { localStorage.clear(); document.documentElement.removeAttribute("data-theme"); });

test("defaults to warm (no data-theme) and toggles to dark, persisting", () => {
  render(<ThemeToggle />);
  expect(document.documentElement.getAttribute("data-theme")).toBe(null);
  fireEvent.click(screen.getByRole("button", { name: /theme/i }));
  expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  expect(localStorage.getItem("theme")).toBe("dark");
  fireEvent.click(screen.getByRole("button", { name: /theme/i }));
  expect(document.documentElement.getAttribute("data-theme")).toBe(null);
  expect(localStorage.getItem("theme")).toBe("warm");
});

test("reads persisted dark on mount", () => {
  localStorage.setItem("theme", "dark");
  render(<ThemeToggle />);
  expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
});
