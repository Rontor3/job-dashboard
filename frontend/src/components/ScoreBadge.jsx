import React, { useEffect, useState } from "react";

export default function ScoreBadge({ value }) {
  const target = value == null ? null : Math.round(value * 100);
  const reduced = typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const [shown, setShown] = useState(reduced ? target : 0);

  useEffect(() => {
    if (target == null || reduced) { setShown(target); return; }
    let raf, start = null;
    const step = (ts) => {
      if (start == null) start = ts;
      const p = Math.min((ts - start) / 900, 1);
      setShown(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, reduced]);

  if (target == null) return <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>—</span>;
  return (
    <span style={{ fontSize: 16, fontWeight: 700, color: "var(--green)", minWidth: 26, textAlign: "right" }}>
      {shown}
    </span>
  );
}
