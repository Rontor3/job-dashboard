import React, { useCallback, useEffect, useState } from "react";
import { fetchLayouts, deleteVersion, loadVersion, saveVersion, layoutPdfUrl } from "../api.js";

const CARD = {
  background: "var(--card)", border: "0.5px solid var(--hairline)",
  borderRadius: "var(--radius-card)", padding: "16px 18px", marginBottom: 12,
};
const BTN = {
  border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px",
  borderRadius: "var(--radius-pill)", fontWeight: 500,
};
const OPEN = { ...BTN, background: "var(--green)", color: "#FFFFFF", textDecoration: "none" };
const GHOST = { ...BTN, background: "var(--canvas)", color: "var(--ink)", border: "0.5px solid var(--hairline)" };

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function TitleChips({ titles }) {
  if (!titles || titles.length === 0) return null;
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
      {titles.map((t, i) => (
        <span key={i} style={{ fontSize: 11, background: "#F1EBE0", color: "var(--ink-soft)", padding: "2px 9px", borderRadius: "var(--radius-pill)" }}>
          {t}
        </span>
      ))}
    </div>
  );
}

export default function ResumeLibrary() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    fetchLayouts().then(setData).catch((e) => setError(String(e)));
  }, []);
  useEffect(() => { load(); }, [load]);

  const handleDelete = (name) => {
    if (!window.confirm(`Delete résumé version “${name}”? This can't be undone.`)) return;
    setBusy(true);
    deleteVersion(name).then(load).catch((e) => setError(String(e))).finally(() => setBusy(false));
  };

  const handleRename = (name) => {
    const next = window.prompt(`Rename “${name}” to:`, name);
    if (!next || !next.trim() || next.trim() === name) return;
    setBusy(true);
    loadVersion(name)
      .then((blocks) => saveVersion(next.trim(), blocks))
      .then(() => deleteVersion(name))
      .then(load)
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false));
  };

  if (error) return <div style={{ color: "var(--dupe-ink)", padding: 16 }}>{error}</div>;
  if (!data) return <div style={{ color: "var(--ink-soft)", padding: 16 }}>Loading your résumés…</div>;

  const versions = data.versions || [];
  const workingBlocks = (data.working || []).filter((b) => !b.excluded);
  const workingTitles = workingBlocks.map((b) => b.title).filter(Boolean);

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)", margin: 0 }}>Custom résumés</h2>
        <span style={{ fontSize: 12, color: "var(--ink-soft)" }}>
          {versions.length} saved version{versions.length === 1 ? "" : "s"}
        </span>
      </div>
      <p style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 0 }}>
        Every version you save in a job’s <b>Tailor résumé</b> editor is stored here in the dashboard. Open any as a PDF, rename, or delete.
      </p>

      {/* Working draft — always present, your latest edits */}
      <div style={{ ...CARD, borderColor: "var(--green)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>
              Working draft
              <span style={{ fontSize: 11, color: "var(--green)", background: "var(--green-tint)", padding: "1px 8px", borderRadius: "var(--radius-pill)", marginLeft: 6 }}>
                auto-saved
              </span>
            </div>
            <div style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 4 }}>
              {workingBlocks.length} block{workingBlocks.length === 1 ? "" : "s"} · your latest editor state
            </div>
          </div>
          <a href={layoutPdfUrl("__working__")} target="_blank" rel="noreferrer" style={OPEN}>Open PDF ↗</a>
        </div>
        <TitleChips titles={workingTitles} />
      </div>

      {versions.length === 0 ? (
        <div style={{ ...CARD, color: "var(--ink-soft)", fontSize: 13 }}>
          No saved versions yet. In a job’s <b>Tailor résumé</b> editor, click <b>Save version</b> to keep a named copy here.
        </div>
      ) : (
        versions.map((v) => {
          const s = v.summary || {};
          const n = s.block_count ?? 0;
          return (
            <div key={v.id} style={CARD}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>{v.name}</div>
                  <div style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 4 }}>
                    {n} block{n === 1 ? "" : "s"} · saved {fmtDate(v.updated_at)}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <a href={layoutPdfUrl(v.name)} target="_blank" rel="noreferrer" style={OPEN}>Open PDF ↗</a>
                  <button disabled={busy} onClick={() => handleRename(v.name)} style={GHOST}>Rename</button>
                  <button disabled={busy} onClick={() => handleDelete(v.name)}
                    style={{ ...BTN, background: "transparent", color: "var(--dupe-ink)", border: "0.5px solid var(--hairline)" }}>
                    Delete
                  </button>
                </div>
              </div>
              <TitleChips titles={s.titles} />
            </div>
          );
        })
      )}
    </div>
  );
}
