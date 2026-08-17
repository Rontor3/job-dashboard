import React, { useCallback, useEffect, useState } from "react";
import { fetchLayouts, fetchSegments, deleteVersion, loadVersion, saveVersion, layoutPdfUrl } from "../api.js";
import BlockEditor from "./BlockEditor.jsx";

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
const DANGER = { ...BTN, background: "transparent", color: "var(--dupe-ink)", border: "0.5px solid var(--hairline)" };
const INPUT = {
  fontSize: 13, padding: "6px 10px", border: "0.5px solid var(--hairline)",
  borderRadius: 8, background: "var(--card)", color: "var(--ink)", minWidth: 180,
};

// A brand-new résumé starts from the candidate's base résumé — the default
// segments in manifest order — in the persisted layout shape, so the editor
// (and the PDF renderer) treat it exactly like a saved version.
const NEW_KINDS = ["experience", "project", "skills"];
function seedFromSegments(segs) {
  return (segs || [])
    .filter((s) => NEW_KINDS.includes(s.kind) && s.default !== false)
    .map((s) => ({
      kind: s.kind, title: s.title || "", bullets: s.bullets || [],
      excluded: false, source: "segment", segment_id: s.id,
      group: s.group || null, roleHeader: !!s.role_header,
    }));
}

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
  const [segments, setSegments] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(null);  // { name, label, blocks } | null
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState(null); // { name, value } | null
  const [confirmDel, setConfirmDel] = useState(null); // name | null

  const load = useCallback(() => {
    fetchLayouts().then(setData).catch((e) => setError(String(e)));
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { fetchSegments().then(setSegments).catch(() => setSegments([])); }, []);

  const versionsList = (data && data.versions) || [];

  const openEditor = (name, label, blocks) => {
    setError(null);
    setEditing({ name, label, blocks: blocks || [] });
  };
  const handleEditVersion = (name) => {
    loadVersion(name)
      .then((blocks) => openEditor(name, name, blocks))
      .catch((e) => setError(String(e)));
  };

  const startNew = () => { setError(null); setNewName(""); setCreating(true); };
  const createNew = () => {
    const name = newName.trim();
    if (!name || !segments) return;
    if (name === "__working__") { setError("That name is reserved — pick another."); return; }
    if (versionsList.some((v) => v.name === name)) { setError(`A version named “${name}” already exists.`); return; }
    setBusy(true); setError(null);
    const seed = seedFromSegments(segments);
    saveVersion(name, seed)
      .then(() => { setCreating(false); setNewName(""); load(); openEditor(name, name, seed); })
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false));
  };

  const doRename = () => {
    if (!renaming) return;
    const from = renaming.name;
    const to = renaming.value.trim();
    if (!to || to === from) { setRenaming(null); return; }
    if (to === "__working__") { setError("That name is reserved — pick another."); return; }
    if (versionsList.some((v) => v.name === to)) { setError(`A version named “${to}” already exists.`); return; }
    setBusy(true); setError(null);
    loadVersion(from)
      .then((blocks) => saveVersion(to, blocks))
      .then(() => deleteVersion(from))
      .then(() => { setRenaming(null); load(); })
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false));
  };

  const doDelete = (name) => {
    setBusy(true); setError(null);
    deleteVersion(name)
      .then(() => { setConfirmDel(null); load(); })
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false));
  };

  if (!data) {
    return (
      <div style={{ padding: 16, color: error ? "var(--dupe-ink)" : "var(--ink-soft)" }}>
        {error || "Loading your résumés…"}
      </div>
    );
  }

  const versions = data.versions || [];
  const workingBlocks = (data.working || []).filter((b) => !b.excluded);
  const workingTitles = workingBlocks.map((b) => b.title).filter(Boolean);

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)", margin: 0 }}>Custom résumés</h2>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 12, color: "var(--ink-soft)" }}>
            {versions.length} saved version{versions.length === 1 ? "" : "s"}
          </span>
          {!editing && !creating && (
            <button onClick={startNew} disabled={busy || !segments}
              title={segments ? "Create a new résumé from your base résumé" : "Loading…"}
              style={{ ...OPEN, cursor: busy || !segments ? "default" : "pointer", opacity: busy || !segments ? 0.6 : 1 }}>
              + New résumé
            </button>
          )}
        </div>
      </div>
      <p style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 0 }}>
        Every version you save in a job’s <b>Tailor résumé</b> editor is stored here in the dashboard. <b>+ New résumé</b> starts a fresh one from your base résumé. Edit any version, open it as a PDF, rename, or delete.
      </p>

      {error && (
        <div style={{ background: "var(--dupe-bg)", color: "var(--dupe-ink)", fontSize: 12, borderRadius: 10, padding: "8px 12px", marginBottom: 10 }}>
          {error}
        </div>
      )}

      {/* Inline new-résumé form (no native prompt — works everywhere) */}
      {!editing && creating && (
        <div style={{ ...CARD, borderColor: "var(--green)", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>New résumé:</span>
          <input
            autoFocus
            aria-label="New résumé name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") createNew(); if (e.key === "Escape") { setCreating(false); setNewName(""); } }}
            placeholder="Name it (e.g. ML-Engineer, FAANG, Fintech…)"
            style={INPUT}
          />
          <button onClick={createNew} disabled={busy || !newName.trim() || !segments}
            style={{ ...OPEN, opacity: busy || !newName.trim() || !segments ? 0.6 : 1 }}>
            Create &amp; edit
          </button>
          <button onClick={() => { setCreating(false); setNewName(""); }} style={GHOST}>Cancel</button>
          <span style={{ fontSize: 11, color: "var(--ink-faint)" }}>Starts from your base résumé.</span>
        </div>
      )}

      {editing ? (
        <div style={CARD}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>
              Editing: {editing.label}
            </div>
            <button onClick={() => { setEditing(null); load(); }} style={GHOST}>← Back to library</button>
          </div>
          <div style={{ fontSize: 12, color: "var(--ink-soft)" }}>
            Edits auto-save to this version. Highlight keywords, add/remove/reorder and edit blocks, then <b>Save &amp; open PDF</b> to render it. (Rewrite needs a job’s JD, so it stays in a job’s Tailor-résumé panel.)
          </div>
          {segments ? (
            <BlockEditor
              jobId={null}
              standalone
              autoSaveName={editing.name}
              suggestion={{ segments, working: editing.blocks, versions }}
              generating={false}
              hasDraft={false}
              onGenerate={(name) => window.open(layoutPdfUrl(name), "_blank", "noopener")}
              onCancel={() => { setEditing(null); load(); }}
            />
          ) : (
            <div style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 8 }}>Loading editor…</div>
          )}
        </div>
      ) : (
        <>
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
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button onClick={() => openEditor("__working__", "Working draft", data.working || [])} style={GHOST}>Edit</button>
                <a href={layoutPdfUrl("__working__")} target="_blank" rel="noreferrer" style={OPEN}>Open PDF ↗</a>
              </div>
            </div>
            <TitleChips titles={workingTitles} />
          </div>

          {versions.length === 0 ? (
            <div style={{ ...CARD, color: "var(--ink-soft)", fontSize: 13 }}>
              No saved versions yet. Click <b>+ New résumé</b> above, or in a job’s <b>Tailor résumé</b> editor click <b>Save version</b>.
            </div>
          ) : (
            versions.map((v) => {
              const s = v.summary || {};
              const n = s.block_count ?? 0;
              const isRenaming = renaming && renaming.name === v.name;
              return (
                <div key={v.id} style={CARD}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <div>
                      {isRenaming ? (
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          <input
                            autoFocus
                            aria-label={`Rename ${v.name}`}
                            value={renaming.value}
                            onChange={(e) => setRenaming({ name: v.name, value: e.target.value })}
                            onKeyDown={(e) => { if (e.key === "Enter") doRename(); if (e.key === "Escape") setRenaming(null); }}
                            style={INPUT}
                          />
                          <button onClick={doRename} disabled={busy} style={{ ...OPEN, opacity: busy ? 0.6 : 1 }}>Save</button>
                          <button onClick={() => setRenaming(null)} style={GHOST}>Cancel</button>
                        </div>
                      ) : (
                        <>
                          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>{v.name}</div>
                          <div style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 4 }}>
                            {n} block{n === 1 ? "" : "s"} · saved {fmtDate(v.updated_at)}
                          </div>
                        </>
                      )}
                    </div>
                    {!isRenaming && (
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        {confirmDel === v.name ? (
                          <>
                            <span style={{ fontSize: 12, color: "var(--dupe-ink)", alignSelf: "center" }}>Delete “{v.name}”?</span>
                            <button onClick={() => doDelete(v.name)} disabled={busy} style={{ ...DANGER, opacity: busy ? 0.6 : 1 }}>Confirm delete</button>
                            <button onClick={() => setConfirmDel(null)} style={GHOST}>Cancel</button>
                          </>
                        ) : (
                          <>
                            <button disabled={busy} onClick={() => handleEditVersion(v.name)} style={GHOST}>Edit</button>
                            <a href={layoutPdfUrl(v.name)} target="_blank" rel="noreferrer" style={OPEN}>Open PDF ↗</a>
                            <button disabled={busy} onClick={() => { setError(null); setRenaming({ name: v.name, value: v.name }); }} style={GHOST}>Rename</button>
                            <button disabled={busy} onClick={() => { setError(null); setConfirmDel(v.name); }} style={DANGER}>Delete</button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  <TitleChips titles={s.titles} />
                </div>
              );
            })
          )}
        </>
      )}
    </div>
  );
}
