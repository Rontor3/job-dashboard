import React, { useEffect, useId, useState } from "react";
import { fetchQbankEntries } from "../api.js";

const MAX_SHOWN = 8;

// Pick a questionnaire entry by typing. Our own list, not a <datalist>: the browser's cuts long questions to one line
// and has no way to show the rest, so you couldn't tell two similar ones apart. Here each match wraps in full.
// onChange receives the entry id once one is picked (or the text is exactly an entry's question), else null.
export default function EntryPicker({ id, label, onChange }) {
  const [entries, setEntries] = useState([]);
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState(0);
  const auto = useId();
  const listId = `${id || auto}-list`;
  useEffect(() => { fetchQbankEntries().then(setEntries).catch(() => setEntries([])); }, []);

  const words = text.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = words.length
    ? entries.filter((e) => words.every((w) => e.question.toLowerCase().includes(w))).slice(0, MAX_SHOWN)
    : [];
  const type = (v) => {
    setText(v);
    setOpen(true);
    setAt(0);
    const hit = entries.find((e) => e.question === v || e.id === v);
    onChange(hit ? hit.id : null);
  };
  const choose = (e) => { setText(e.question); setOpen(false); onChange(e.id); };
  const keys = (ev) => {
    if (!open || !matches.length) return;
    if (ev.key === "ArrowDown") { ev.preventDefault(); setAt((i) => Math.min(i + 1, matches.length - 1)); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); setAt((i) => Math.max(i - 1, 0)); }
    else if (ev.key === "Enter") { ev.preventDefault(); choose(matches[at]); }
    else if (ev.key === "Escape") setOpen(false);
  };
  const showing = open && matches.length > 0;
  return (
    <div className="entry-picker">
      <input aria-label={label} role="combobox" aria-expanded={showing} aria-controls={listId} aria-autocomplete="list"
             value={text} title={text} placeholder="Type to find the question…"
             onChange={(e) => type(e.target.value)} onKeyDown={keys} onFocus={() => setOpen(true)}
             onBlur={() => setTimeout(() => setOpen(false), 120)} />
      {showing && (
        <ul id={listId} role="listbox" className="entry-picker-list">
          {matches.map((e, i) => (
            <li key={e.id} role="option" aria-selected={i === at} className={i === at ? "on" : ""}
                onMouseDown={(ev) => { ev.preventDefault(); choose(e); }} onMouseEnter={() => setAt(i)}>
              {e.question}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
