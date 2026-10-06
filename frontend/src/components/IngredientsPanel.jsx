import React, { useEffect, useState } from "react";
import { fetchIngredients, saveIngredient } from "../api.js";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "5px 12px", borderRadius: "var(--radius-pill)" };
const INPUT = { fontSize: 12, padding: "6px 10px", border: "0.5px solid var(--hairline)", borderRadius: 8, background: "var(--canvas)", color: "var(--ink)", width: "100%", boxSizing: "border-box" };
const CARD = { background: "var(--card)", border: "0.5px solid var(--hairline)", borderRadius: 10, padding: "10px 14px" };
const lines = (v) => (v || []).join("\n");
const split = (t, sep) => t.split(sep).map((x) => x.trim()).filter(Boolean);

function Unit({ u, onSaved }) {
  const [f, setF] = useState({
    title: u.title || "", org: u.org || "", problem: u.problem || "", approach: u.approach || "",
    tech: (u.tech || []).join(", "), impact: lines(u.impact), tags: (u.tags || []).join(", "),
  });
  const [source, setSource] = useState(u.source || "");
  const [unlocked, setUnlocked] = useState(false);
  const [msg, setMsg] = useState("");
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const field = (k, label, area) => (
    <label style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 11, color: "var(--ink-soft)" }}>
      {label}
      {area ? <textarea aria-label={`${label} of ${u.title}`} rows={3} value={f[k]} onChange={set(k)} style={INPUT} />
            : <input aria-label={`${label} of ${u.title}`} value={f[k]} onChange={set(k)} style={INPUT} />}
    </label>
  );
  const save = () => {
    const body = { title: f.title, org: f.org, problem: f.problem, approach: f.approach,
                   tech: split(f.tech, ","), impact: split(f.impact, "\n"), tags: split(f.tags, ",") };
    if (unlocked && source !== (u.source || "")) { body.source = source; body.confirm_source = true; }
    saveIngredient(u.id, body).then((saved) => { setMsg("Saved"); setUnlocked(false); onSaved(saved); setTimeout(() => setMsg(""), 1500); })
      .catch((e) => setMsg(String(e)));
  };
  return (
    <div data-testid={`ingredient-${u.id}`} style={{ ...CARD, display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>{u.type}</div>
      {field("title", "Title")}{field("org", "Organisation")}
      {field("problem", "Problem", true)}{field("approach", "Approach", true)}
      {field("tech", "Tech (comma separated)")}{field("impact", "Impact (one per line)", true)}
      {field("tags", "Tags (comma separated)")}
      <label style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 11, color: "var(--ink-soft)" }}>
        Source — verbatim text the agent copies word for word {unlocked ? "(editing)" : "(locked)"}
        <textarea aria-label={`Source of ${u.title}`} rows={4} value={source} readOnly={!unlocked}
                  onChange={(e) => setSource(e.target.value)} style={{ ...INPUT, opacity: unlocked ? 1 : 0.6 }} />
      </label>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button aria-label={`Save ${u.title}`} onClick={save} style={{ ...BTN, background: "var(--green)", color: "#fff" }}>Save</button>
        <button aria-label={`Unlock source of ${u.title}`} onClick={() => setUnlocked(!unlocked)}
                style={{ ...BTN, background: "var(--canvas)", color: "var(--ink-soft)", border: "0.5px solid var(--hairline)" }}>
          {unlocked ? "Lock source" : "Unlock source"}
        </button>
        {msg && <span role="status" style={{ fontSize: 12, color: "var(--ink-soft)" }}>{msg}</span>}
      </div>
    </div>
  );
}

export default function IngredientsPanel() {
  const [d, setD] = useState(null);
  useEffect(() => { fetchIngredients().then(setD).catch(() => setD({ units: [] })); }, []);
  if (!d || !d.units.length) return null;
  const replace = (saved) => setD({ ...d, units: d.units.map((x) => (x.id === saved.id ? saved : x)) });
  return (
    <section style={{ marginTop: 18 }}>
      <h3 style={{ fontSize: 13, color: "var(--ink-soft)", margin: "8px 0" }}>
        Ingredients ({d.units.length}) — your projects and roles, the material long answers are written from
      </h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {d.units.map((u) => <Unit key={u.id} u={u} onSaved={replace} />)}
      </div>
    </section>
  );
}
