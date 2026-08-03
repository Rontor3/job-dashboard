import { expect, test } from "vitest";
import { cleanJd } from "../cleanJd.js";

test("removes markdown escape backslashes", () => {
  expect(cleanJd("cutting\\-edge, R1013045\\), Machine Learning\\/Deep")).toBe(
    "cutting-edge, R1013045), Machine Learning/Deep"
  );
});

test("strips ** bold markers", () => {
  expect(cleanJd("**About Us** and text")).toBe("About Us and text");
});

test("returns empty string for null/undefined", () => {
  expect(cleanJd(null)).toBe("");
  expect(cleanJd(undefined)).toBe("");
});

test("collapses runs of blank lines", () => {
  expect(cleanJd("a\n\n\n\nb")).toBe("a\n\nb");
});
