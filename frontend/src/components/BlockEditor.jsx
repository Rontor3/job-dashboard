import React, { useState } from "react";
import { regenerateBlock } from "../api.js";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px", borderRadius: "var(--radius-pill)", transition: "transform var(--dur-quick) ease-out" };
const SMALL_BTN = { ...BTN, fontSize: 11, padding: "4px 10px" };

const KIND_ORDER = ["skills", "experience", "project"];
const KIND_LABELS = { skills: "Skills", experience: "Experience", project: "Projects" };
const ADD_LABELS = { skills: "+ add skill group", experience: "+ add role", project: "+ add project" };

let customBlockCounter = 0;

function buildInitialBlocks(suggestion) {
  const segmentMap = {};
  (suggestion.segments || []).forEach((seg) => {
    segmentMap[seg.id] = seg;
  });
  const ids = suggestion.block_ids || [];
  return ids
    .map((id) => segmentMap[id])
    .filter((seg) => seg && KIND_ORDER.includes(seg.kind))
    .map((seg) => ({
      key: seg.id,
      kind: seg.kind,
      title: seg.title,
      segment_id: seg.id,
      source: "segment",
      active: 0,
      variants: [{ label: "Original", bullets: seg.bullets || [] }],
    }));
}

function activeBulletsOf(block) {
  return block.variants[block.active]?.bullets || [];
}

function renderBulletText(text) {
  const parts = String(text).split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      <React.Fragment key={i}>{part}</React.Fragment>
    )
  );
}

export default function BlockEditor({ jobId, suggestion, generating, onGenerate, onCancel }) {
  const [blocks, setBlocks] = useState(() => buildInitialBlocks(suggestion));
  const [editingKey, setEditingKey] = useState(null);
  const [editTitle, setEditTitle] = useState("");
  const [editBullets, setEditBullets] = useState("");
  const [regeneratingKey, setRegeneratingKey] = useState(null);
  const [regenFailedKeys, setRegenFailedKeys] = useState(new Set());
  const [dragKey, setDragKey] = useState(null);
  const [layoutError, setLayoutError] = useState(null);

  const updateBlock = (key, updater) => {
    setBlocks((prev) => prev.map((b) => (b.key === key ? updater(b) : b)));
  };

  const clearRegenFailure = (key) => {
    setRegenFailedKeys((prev) => {
      if (!prev.has(key)) return prev;
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  };

  const handleRegenerate = (block) => {
    setRegeneratingKey(block.key);
    clearRegenFailure(block.key);
    regenerateBlock(jobId, { kind: block.kind, title: block.title, bullets: activeBulletsOf(block) })
      .then((res) => {
        const alternatives = res.alternatives || [];
        if (alternatives.length === 0) {
          setRegenFailedKeys((prev) => new Set(prev).add(block.key));
          return;
        }
        updateBlock(block.key, (b) => {
          const kept = b.variants.filter((v) => !v.label.startsWith("Alternative"));
          return {
            ...b,
            active: 0,
            variants: [
              ...kept,
              ...alternatives.map((bullets, idx) => ({ label: `Alternative ${idx + 1}`, bullets })),
            ],
          };
        });
      })
      .catch(() => setRegenFailedKeys((prev) => new Set(prev).add(block.key)))
      .finally(() => setRegeneratingKey(null));
  };

  const pickVariant = (block, idx) => updateBlock(block.key, (b) => ({ ...b, active: idx }));

  const startEdit = (block) => {
    setEditingKey(block.key);
    setEditTitle(block.title);
    setEditBullets(activeBulletsOf(block).join("\n"));
  };

  const cancelEdit = (block) => {
    setEditingKey(null);
    if (block.source === "custom" && block.title === "" && activeBulletsOf(block).length === 0) {
      setBlocks((prev) => prev.filter((b) => b.key !== block.key));
    }
  };

  const saveEdit = (block) => {
    const bullets = editBullets
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    updateBlock(block.key, (b) => {
      const variants = [b.variants[0], { label: "Your edit", bullets }];
      return { ...b, title: editTitle, variants, active: variants.length - 1 };
    });
    setEditingKey(null);
  };

  const addBlock = (kind) => {
    customBlockCounter += 1;
    const key = `custom-${kind}-${customBlockCounter}`;
    const block = {
      key,
      kind,
      title: "",
      segment_id: null,
      source: "custom",
      active: 0,
      variants: [{ label: "Original", bullets: [] }],
    };
    setBlocks((prev) => [...prev, block]);
    setEditingKey(key);
    setEditTitle("");
    setEditBullets("");
  };

  const deleteBlock = (key) => {
    setBlocks((prev) => prev.filter((b) => b.key !== key));
    clearRegenFailure(key);
    if (editingKey === key) setEditingKey(null);
  };

  const handleDragStart = (e, block) => {
    setDragKey(block.key);
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", block.key);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
  };

  const handleDrop = (e, targetBlock) => {
    e.preventDefault();
    const sourceKey = dragKey || (e.dataTransfer && e.dataTransfer.getData("text/plain"));
    setDragKey(null);
    if (!sourceKey || sourceKey === targetBlock.key) return;
    setBlocks((prev) => {
      const source = prev.find((b) => b.key === sourceKey);
      if (!source || source.kind !== targetBlock.kind) return prev;
      const withoutSource = prev.filter((b) => b.key !== sourceKey);
      const targetIdx = withoutSource.findIndex((b) => b.key === targetBlock.key);
      withoutSource.splice(targetIdx, 0, source);
      return withoutSource;
    });
  };

  // Emit blocks grouped by kind (Skills → Experience → Projects) so the
  // generated PDF's section order matches what the editor displays, not the
  // relevance-score order the suggestion arrived in.
  const buildLayout = () =>
    KIND_ORDER.flatMap((kind) =>
      blocks
        .filter((b) => b.kind === kind)
        .map((b) => {
          if (b.source === "segment" && b.active === 0) {
            return { segment_id: b.segment_id };
          }
          // A skills/project segment block carries its bold résumé label
          // inside the bullets (**label**); sending the manifest title too
          // would double the heading. Custom (added) and experience blocks
          // keep their title.
          const dropTitle =
            b.source === "segment" && (b.kind === "skills" || b.kind === "project");
          return { kind: b.kind, title: dropTitle ? "" : b.title, bullets: activeBulletsOf(b) };
        })
    );

  const handleGenerateClick = () => {
    if (blocks.length === 0) {
      setLayoutError("Add at least one block");
      return;
    }
    setLayoutError(null);
    onGenerate(buildLayout());
  };

  const groups = KIND_ORDER.map((kind) => ({
    kind,
    label: KIND_LABELS[kind],
    items: blocks.filter((b) => b.kind === kind),
  }));

  return (
    <div style={{ marginTop: 12, borderTop: "0.5px solid var(--hairline)", paddingTop: 12 }}>
      {layoutError && (
        <div style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{layoutError}</div>
      )}

      {groups.map((group) => (
        <div key={group.kind} style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)" }}>{group.label}</div>
            <button
              onClick={() => addBlock(group.kind)}
              style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--green)" }}
            >
              {ADD_LABELS[group.kind]}
            </button>
          </div>

          {group.items.length === 0 && (
            <div style={{ fontSize: 11, color: "var(--ink-faint)", fontStyle: "italic" }}>No blocks</div>
          )}

          {group.items.map((block) => (
            <div
              key={block.key}
              draggable
              onDragStart={(e) => handleDragStart(e, block)}
              onDragOver={handleDragOver}
              onDrop={(e) => handleDrop(e, block)}
              style={{
                border: "0.5px solid var(--hairline)",
                borderRadius: 10,
                padding: 10,
                marginBottom: 8,
                background: "var(--card)",
              }}
            >
              {editingKey === block.key ? (
                <div>
                  <input
                    aria-label="Block title"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    placeholder="Title"
                    style={{ width: "100%", fontSize: 12, marginBottom: 6, padding: 6, boxSizing: "border-box" }}
                  />
                  <textarea
                    aria-label="Block bullets"
                    value={editBullets}
                    onChange={(e) => setEditBullets(e.target.value)}
                    placeholder="One bullet per line"
                    rows={4}
                    style={{ width: "100%", fontSize: 12, padding: 6, boxSizing: "border-box" }}
                  />
                  <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                    <button onClick={() => saveEdit(block)} style={{ ...SMALL_BTN, background: "var(--green)", color: "#FFFFFF" }}>
                      Save
                    </button>
                    <button onClick={() => cancelEdit(block)} style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--ink-faint)" }}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, color: "var(--ink)" }}>
                      {block.title || "(untitled)"}
                    </div>
                    <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                      <button
                        onClick={() => handleRegenerate(block)}
                        disabled={regeneratingKey === block.key}
                        style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--green)" }}
                      >
                        {regeneratingKey === block.key ? "Regenerating…" : "Regenerate"}
                      </button>
                      <button onClick={() => startEdit(block)} style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--ink)" }}>
                        Edit
                      </button>
                      <button onClick={() => deleteBlock(block.key)} style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--dupe-ink)" }}>
                        Delete
                      </button>
                    </div>
                  </div>

                  <ul style={{ margin: "6px 0 0", paddingLeft: 16, fontSize: 12, color: "var(--ink-soft)" }}>
                    {activeBulletsOf(block).map((bullet, i) => (
                      <li key={i}>{renderBulletText(bullet)}</li>
                    ))}
                  </ul>

                  {block.variants.length > 1 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                      {block.variants.map((variant, idx) => (
                        <button
                          key={`${variant.label}-${idx}`}
                          onClick={() => pickVariant(block, idx)}
                          style={{
                            ...SMALL_BTN,
                            border: "0.5px solid var(--hairline)",
                            background: block.active === idx ? "var(--green-tint)" : "var(--canvas)",
                            color: block.active === idx ? "var(--green)" : "var(--ink-faint)",
                          }}
                        >
                          {variant.label}
                        </button>
                      ))}
                    </div>
                  )}

                  {regenFailedKeys.has(block.key) && (
                    <div style={{ fontSize: 11, color: "var(--ink-faint)", fontStyle: "italic", marginTop: 4 }}>
                      couldn't generate — keep editing
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      ))}

      {/* Live preview */}
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 6 }}>Preview</div>
        <div style={{ background: "var(--canvas)", border: "0.5px solid var(--hairline)", borderRadius: 10, padding: 10 }}>
          {blocks.length === 0 && (
            <div style={{ fontSize: 11, color: "var(--ink-faint)", fontStyle: "italic" }}>No blocks selected</div>
          )}
          {blocks.map((block) => (
            <div key={block.key} style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)" }}>{block.title || "(untitled)"}</div>
              <ul style={{ margin: "2px 0 0", paddingLeft: 16, fontSize: 11, color: "var(--ink-soft)" }}>
                {activeBulletsOf(block).map((bullet, i) => (
                  <li key={i}>{renderBulletText(bullet)}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={handleGenerateClick}
          disabled={generating}
          style={{ ...BTN, background: "var(--green)", color: "#FFFFFF" }}
        >
          {generating ? "Generating…" : "Generate tailored resume"}
        </button>
        <button onClick={onCancel} style={{ ...BTN, background: "var(--canvas)", color: "var(--ink-faint)" }}>
          Cancel
        </button>
      </div>
    </div>
  );
}
