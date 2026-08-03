import { render, screen, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import BrowseOverview from "../components/BrowseOverview.jsx";

const stats = {
  verdict_counts: { "Strong Fit": 42, "Good Fit": 88, "Moderate Fit": 30 },
  top_industries: [{ industry: "BFSI", count: 107 }, { industry: "Fintech", count: 353 }],
};

test("shows Strong/Good counts and industry segments; click filters", () => {
  const onIndustry = vi.fn();
  render(<BrowseOverview stats={stats} onIndustry={onIndustry} />);
  expect(screen.getByText("42")).toBeInTheDocument();
  expect(screen.getByText("88")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /BFSI/ }));
  expect(onIndustry).toHaveBeenCalledWith("BFSI");
});

test("renders nothing without stats", () => {
  const { container } = render(<BrowseOverview stats={null} onIndustry={() => {}} />);
  expect(container.firstChild).toBeNull();
});
