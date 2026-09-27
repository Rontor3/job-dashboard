import React, { useEffect, useState } from "react";
import { hiringPosts, refreshHiring, dismissHiring, promoteHiring, draftHiringEmail, createHiringCv } from "../api.js";

const CHIP = { fontSize: 11, padding: "3px 10px", borderRadius: "var(--radius-pill)",
  border: "0.5px solid var(--hairline)", color: "var(--ink-soft)", textDecoration: "none" };

function Contacts({ c, onEmail }) {
  if (!c) return null;
  const host = (u) => { try { return new URL(u).host; } catch { return u; } };
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
      {c.forms.map((u) => <a key={u} href={u} target="_blank" rel="noreferrer" style={CHIP}>📝 Form · {host(u)}</a>)}
      {c.emails.map((e) => (
        <a key={e} href={`mailto:${e}`} style={CHIP} title="Open a drafted email in Gmail"
          onClick={(ev) => { ev.preventDefault(); onEmail(e); }}>✉️ {e}</a>
      ))}
      {c.links.map((u) => <a key={u} href={u} target="_blank" rel="noreferrer" style={CHIP}>🔗 {host(u)}</a>)}
      {c.phones.map((p) => <a key={p} href={`tel:${p}`} style={CHIP}>📞 {p}</a>)}
      {c.dm && <span style={CHIP}>💬 DM on LinkedIn</span>}
    </div>
  );
}

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px",
  borderRadius: "var(--radius-pill)", background: "var(--green)", color: "#fff" };

export default function HiringSignals({ onOpenJob = () => {} }) {
  const [posts, setPosts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = () => hiringPosts().then((d) => setPosts(d.posts || [])).catch(() => {});
  useEffect(() => { load(); }, []);

  const onRefresh = () => {
    setBusy(true); setError(null);
    refreshHiring().then(load).catch((e) => setError(e.message)).finally(() => setBusy(false));
  };
  const [note, setNote] = useState({});
  const say = (id, msg) => setNote((n) => ({ ...n, [id]: msg }));
  const onResearch = (id) => {
    say(id, "Researching company & drafting letter… (1–2 min)");
    promoteHiring(id).then(() => { say(id, "Research done"); load(); }).catch((e) => say(id, e.message));
  };
  const onCv = (id) => {
    say(id, "Building CV for this job… (1–3 min)");
    createHiringCv(id).then((d) => { say(id, "CV ready"); window.open(d.pdf_url, "_blank"); load(); })
      .catch((e) => say(id, e.message));
  };
  const onDraft = (id, to) => {
    // Open the tab inside the click so the browser doesn't block it as a popup.
    const tab = window.open("about:blank", "_blank");
    say(id, "Drafting…");
    draftHiringEmail(id, to).then((d) => {
      if (tab) tab.location.href = d.gmail_url; else window.open(d.gmail_url, "_blank");
      say(id, d.attached ? `Gmail draft to ${d.to} — ${d.attached} attached`
                         : `Gmail opened for ${d.to} — attach your résumé before sending`);
    }).catch((e) => { if (tab) tab.close(); say(id, e.message); });
  };
  const onDismiss = (id) => {
    setPosts((p) => p.filter((x) => x.id !== id));
    dismissHiring(id).catch(() => {});
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 13, color: "var(--ink-faint)" }}>
          Individual LinkedIn hiring posts from the last 7 days, ranked for you.
        </div>
        <button style={BTN} onClick={onRefresh} disabled={busy}>
          {busy ? "Searching LinkedIn…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div role="alert" style={{ color: "var(--dupe-ink)", background: "var(--dupe-bg)", borderRadius: 12, padding: "10px 14px", marginBottom: 12 }}>
          {error.includes("re-paste") ? "LinkedIn session expired — re-paste your cookies in .env." : error}
        </div>
      )}

      {posts.length === 0 && !busy && (
        <div style={{ fontSize: 12, color: "var(--ink-faint)", fontStyle: "italic" }}>
          No hiring posts in the last 7 days. Hit Refresh to search LinkedIn.
        </div>
      )}

      {posts.map((p) => (
        <div key={p.id} style={{ border: "0.5px solid var(--hairline)", borderRadius: 12, padding: 12, marginBottom: 10, background: "var(--card)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>{p.poster_name}</div>
              <div style={{ fontSize: 12, color: "var(--ink-faint)" }}>{p.poster_headline}</div>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "flex-start", flexShrink: 0 }}>
              <span style={{ fontSize: 11, color: "var(--green)", fontWeight: 600 }}>
                {Math.round((p.fit_score || 0) * 100)}% fit
              </span>
              <button aria-label="Dismiss" onClick={() => onDismiss(p.id)}
                style={{ border: "none", background: "none", cursor: "pointer", color: "var(--ink-faint)" }}>×</button>
            </div>
          </div>
          {p.fit_reason && (
            <div style={{ fontSize: 12, color: "var(--green)", marginTop: 6 }}>Why: {p.fit_reason}</div>
          )}
          <div style={{ fontSize: 13, color: "var(--ink-soft)", margin: "8px 0" }}>{p.text}</div>
          <Contacts c={p.contacts} onEmail={(e) => onDraft(p.id, e)} />
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
            {!p.job_id ? (
              <button style={BTN} onClick={() => onResearch(p.id)}>Research company</button>
            ) : p.contacts?.emails?.length > 0 ? (
              <button style={BTN} onClick={() => onDraft(p.id)}>Draft email</button>
            ) : p.apply_url ? (
              <a href={p.apply_url} target="_blank" rel="noreferrer" style={{ ...BTN, textDecoration: "none" }}>Apply ↗</a>
            ) : null}
            <button style={{ ...BTN, background: "var(--ink)" }} onClick={() => onCv(p.id)}>Create CV</button>
            {p.resume_id && (
              <a href={`/api/resumes/${p.resume_id}/pdf`} target="_blank" rel="noreferrer"
                style={{ fontSize: 11, color: "var(--green)" }}>CV ↗</a>
            )}
            {p.job_id && (
              <button onClick={() => onOpenJob(p.job_id)}
                style={{ border: "none", background: "none", cursor: "pointer", fontSize: 11, color: "var(--ink-faint)" }}>
                View research</button>
            )}
            {note[p.id] && <span style={{ fontSize: 11, color: "var(--ink-faint)" }}>{note[p.id]}</span>}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--ink-faint)" }}>
            <span>{p.keyword} · {p.posted_at || "recent"}</span>
            <a href={p.url} target="_blank" rel="noreferrer" style={{ color: "var(--green)" }}>View job ↗</a>
          </div>
        </div>
      ))}
    </div>
  );
}
