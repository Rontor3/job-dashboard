import React from "react";

const base = { width: 14, height: 14, viewBox: "0 0 24 24", fill: "none",
               stroke: "currentColor", strokeWidth: 2.5, strokeLinecap: "round",
               strokeLinejoin: "round", "aria-hidden": true };

export const CheckIcon = () => (
  <svg {...base}><path d="M5 13l4 4L19 7" /></svg>
);
export const XIcon = () => (
  <svg {...base}><path d="M6 6l12 12M18 6L6 18" /></svg>
);
export const RefreshIcon = ({ spinning }) => (
  <svg {...base} style={spinning ? { animation: "spin 0.9s linear infinite" } : undefined}>
    <path d="M20 11A8 8 0 1 0 4.6 14M20 11V5m0 6h-6" />
  </svg>
);
export const ChevronIcon = ({ open }) => (
  <svg {...base} style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform var(--dur-quick) ease-out" }}>
    <path d="M6 9l6 6 6-6" />
  </svg>
);
export const ArrowUpRightIcon = () => (
  <svg {...base}><path d="M7 17L17 7M9 7h8v8" /></svg>
);
