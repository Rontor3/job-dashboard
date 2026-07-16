import React, { useEffect, useState } from "react";
import { fetchDuplicates } from "../api.js";
import { ChevronIcon } from "./icons.jsx";

export default function DuplicatesSection() {
  const [dupes, setDupes] = useState([]);
  const [open, setOpen] = useState(false);

  useEffect(() => { fetchDuplicates().then((b) => setDupes(b.duplicates || [])).catch(() => {}); }, []);

  if (!dupes.length) return null;
  return (
    <div style={{ marginTop: 14 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{ border: "none", cursor: "pointer", width: "100%", textAlign: "left", background: "var(--pastel-pink)", color: "var(--pastel-pink-ink)", borderRadius: open ? "12px 12px 0 0" : 12, padding: "11px 16px", fontSize: 13 }}
      >
        Suspected duplicates ({dupes.length}) — kept safe, never deleted <ChevronIcon open={open} />
      </button>
      {open && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, background: "var(--paper)", borderRadius: "0 0 12px 12px" }}>
          {dupes.map((d) => (
            <li key={d.id} style={{ padding: "10px 16px", borderTop: "0.5px solid var(--hairline)", fontSize: 12, color: "var(--ink-soft)" }}>
              {d.title} — {d.company} <span style={{ color: "var(--ink-faint)" }}>({d.source})</span>
              <span style={{ float: "right", color: "var(--pastel-pink-mid)" }}>duplicate of #{d.duplicate_of} · {d.canonical_source}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
