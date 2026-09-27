import React, { useEffect, useState } from "react";
import { fetchQbankEntries } from "../api.js";

const INPUT = { fontSize: 12, padding: "6px 10px", border: "0.5px solid var(--hairline)", borderRadius: 8, background: "var(--canvas)", color: "var(--ink)", width: "100%", boxSizing: "border-box" };

// Pick a questionnaire entry by typing (native <datalist> over the bank).
// onChange receives the entry id once the text matches an entry, else null.
export default function EntryPicker({ id, label, onChange }) {
  const [entries, setEntries] = useState([]);
  const [text, setText] = useState("");
  useEffect(() => { fetchQbankEntries().then(setEntries).catch(() => setEntries([])); }, []);
  const pick = (v) => {
    setText(v);
    const hit = entries.find((e) => e.question === v || e.id === v);
    onChange(hit ? hit.id : null);
  };
  return (
    <>
      <input aria-label={label} list={`${id}-list`} value={text} placeholder="Type to find the question…"
             onChange={(e) => pick(e.target.value)} style={INPUT} />
      <datalist id={`${id}-list`}>
        {entries.map((e) => <option key={e.id} value={e.question} />)}
      </datalist>
    </>
  );
}
