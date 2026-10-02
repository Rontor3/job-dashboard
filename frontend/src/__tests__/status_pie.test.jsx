import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import StatusPie from "../components/StatusPie.jsx";

const STATS = { saved: 2, applied: 5, failed: 1, interviewing: 2, offer: 0, rejected: 0 };

test("one slice per non-empty status, every status in the legend with count and share", () => {
  render(<StatusPie stats={STATS} />);
  for (const k of ["applied", "failed", "interviewing", "saved"]) expect(screen.getByTestId(`pie-slice-${k}`)).toBeInTheDocument();
  expect(screen.queryByTestId("pie-slice-offer")).toBeNull();
  expect(screen.getByTestId("pie-legend-applied").textContent).toContain("Applied550%");
  expect(screen.getByTestId("pie-legend-offer").textContent).toContain("Selected00%");
  expect(screen.getByText("10")).toBeInTheDocument();                      // total in the centre
});

test("hovering a slice shows that status in the centre", () => {
  render(<StatusPie stats={STATS} />);
  fireEvent.mouseEnter(screen.getByTestId("pie-slice-failed"));
  expect(screen.getByText("Failed · 10%")).toBeInTheDocument();
  fireEvent.mouseLeave(screen.getByTestId("pie-slice-failed"));
  expect(screen.getByText("tracked")).toBeInTheDocument();
});

test("a single status draws a full ring; nothing tracked draws the empty track", () => {
  const { rerender, container } = render(<StatusPie stats={{ applied: 3 }} />);
  expect(screen.getByTestId("pie-slice-full")).toBeInTheDocument();
  rerender(<StatusPie stats={{}} />);
  expect(container.querySelectorAll("path")).toHaveLength(0);
  expect(container.querySelector("svg text").textContent).toBe("0");
});
