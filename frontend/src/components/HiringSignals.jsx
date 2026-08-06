import React, { useEffect, useState } from "react";
import { hiringPosts, refreshHiring, dismissHiring } from "../api.js";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px",
  borderRadius: "var(--radius-pill)", background: "var(--green)", color: "#fff" };

export default function HiringSignals() {
  const [posts, setPosts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = () => hiringPosts().then((d) => setPosts(d.posts || [])).catch(() => {});
  useEffect(() => { load(); }, []);

  const onRefresh = () => {
    setBusy(true); setError(null);
    refreshHiring().then(load).catch((e) => setError(e.message)).finally(() => setBusy(false));
  };
  const onDismiss = (id) => {
    setPosts((p) => p.filter((x) => x.id !== id));
    dismissHiring(id).catch(() => {});
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 13, color: "var(--ink-faint)" }}>
          Individual LinkedIn hiring posts from the last 24 hours, ranked for you.
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
          No hiring posts in the last 24 hours. Hit Refresh to search LinkedIn.
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
          <div style={{ fontSize: 13, color: "var(--ink-soft)", margin: "8px 0" }}>{p.text}</div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--ink-faint)" }}>
            <span>{p.keyword} · {p.posted_at || "recent"}</span>
            <a href={p.url} target="_blank" rel="noreferrer" style={{ color: "var(--green)" }}>View on LinkedIn ↗</a>
          </div>
        </div>
      ))}
    </div>
  );
}
