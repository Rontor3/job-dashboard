import React, { useEffect, useRef, useState } from "react";
import {
  regenerateBlock, savedBlocks, saveBlock, generateBullets, suggestSkills,
  highlightBullets, saveWorkingLayout, saveVersion, loadVersion, deleteVersion, fetchLayouts,
} from "../api.js";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px", borderRadius: "var(--radius-pill)", transition: "transform var(--dur-quick) ease-out" };
const SMALL_BTN = { ...BTN, fontSize: 11, padding: "4px 10px" };

const KIND_ORDER = ["experience", "project", "skills"];
const KIND_LABELS = { skills: "Skills", experience: "Experience", project: "Projects" };
const ADD_LABELS = { skills: "+ add skill group", experience: "+ add company", project: "+ add project" };

let customBlockCounter = 0;

function segToBlock(seg) {
  return {
    key: seg.id,
    kind: seg.kind,
    title: seg.title,
    segment_id: seg.id,
    source: "segment",
    active: 0,
    excluded: false,
    group: seg.group || null,           // company (experience nesting)
    roleHeader: !!seg.role_header,       // company role/date header vs sub-project
    variants: [{ label: "Original", bullets: seg.bullets || [] }],
  };
}

// Rebuild editor blocks from a persisted layout (working copy or a version).
function blocksFromLayout(layout) {
  return (layout || [])
    .filter((b) => b && KIND_ORDER.includes(b.kind))
    .map((b, i) => ({
      key: b.segment_id || `saved-${b.kind}-${i}`,
      kind: b.kind,
      title: b.title || "",
      segment_id: b.segment_id || null,
      source: b.source || (b.segment_id ? "segment" : "custom"),
      active: 0,
      excluded: !!b.excluded,
      group: b.group || null,
      roleHeader: !!b.roleHeader,
      variants: [{ label: "Saved", bullets: b.bullets || [] }],
    }));
}

// Serialize the current blocks to a persistable layout.
function layoutFromBlocks(blocks) {
  return blocks.map((b) => ({
    kind: b.kind,
    title: b.title || "",
    bullets: b.variants[b.active]?.bullets || [],
    excluded: !!b.excluded,
    source: b.source,
    segment_id: b.segment_id || null,
    group: b.group || null,
    roleHeader: !!b.roleHeader,
  }));
}

// The default editor set is the candidate's saved working résumé if one exists;
// otherwise the real résumé segments (default:true) in manifest order — NOT
// relevance-score order. Opt-in segments are offered via the "+ add" pickers.
function buildInitialBlocks(suggestion) {
  if (suggestion.working && suggestion.working.length) {
    return blocksFromLayout(suggestion.working);
  }
  return (suggestion.segments || [])
    .filter((seg) => KIND_ORDER.includes(seg.kind) && seg.default !== false)
    .map(segToBlock);
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

export default function BlockEditor({
  jobId, suggestion, generating, hasDraft, onGenerate, onCancel,
  // Standalone (Résumés tab) mode: no job/JD. Edits auto-save to `autoSaveName`
  // (a named version, or the working draft), Rewrite (JD-based) is hidden, and
  // the bottom button saves + opens the version's PDF instead of a job render.
  autoSaveName = "__working__", standalone = false,
}) {
  const saveLayout = (layout) =>
    !autoSaveName || autoSaveName === "__working__"
      ? saveWorkingLayout(layout)
      : saveVersion(autoSaveName, layout);
  const [blocks, setBlocks] = useState(() => buildInitialBlocks(suggestion));
  const [versions, setVersions] = useState(suggestion.versions || []);
  const [versionName, setVersionName] = useState("");
  const [highlightingKey, setHighlightingKey] = useState(null);
  const [editingKey, setEditingKey] = useState(null);
  const [editTitle, setEditTitle] = useState("");
  const [editBullets, setEditBullets] = useState("");
  const [regeneratingKey, setRegeneratingKey] = useState(null);
  const [regenFailedKeys, setRegenFailedKeys] = useState(new Set());
  const [dragKey, setDragKey] = useState(null);
  const [layoutError, setLayoutError] = useState(null);
  const [savedKeys, setSavedKeys] = useState(new Set()); // block.key that are in the library
  const [editDetails, setEditDetails] = useState(""); // rough notes fed to the AI bullet writer
  const [genBusy, setGenBusy] = useState(false);
  const [genFailed, setGenFailed] = useState(false);
  const [bulletCount, setBulletCount] = useState("auto"); // "auto" = one per note; or force 3/4/5
  const [addMenuKind, setAddMenuKind] = useState(null); // which section's "add" picker is open
  const [skillSug, setSkillSug] = useState([]);         // AI-suggested skills (chips)
  const [skillSugBusy, setSkillSugBusy] = useState(false);
  const [skillSugDone, setSkillSugDone] = useState(false);
  const [blockSkillSug, setBlockSkillSug] = useState({}); // per-skill-group suggestions {blockKey: string[]}
  const [blockSkillBusy, setBlockSkillBusy] = useState(null); // blockKey being suggested

  // Auto-save the working résumé whenever blocks change (debounced), so edits,
  // additions, order and exclusions persist across Generate and reopening.
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return; }
    const t = setTimeout(() => {
      saveLayout(layoutFromBlocks(blocks)).catch(() => {});
    }, 600);
    return () => clearTimeout(t);
  }, [blocks]);

  const handleSaveVersion = () => {
    const name = versionName.trim();
    if (!name) return;
    saveVersion(name, layoutFromBlocks(blocks))
      .then(() => fetchLayouts())
      .then((l) => setVersions(l.versions || []))
      .catch(() => {});
    setVersionName("");
  };

  const handleLoadVersion = (name) => {
    if (!name) return;
    loadVersion(name).then((layout) => setBlocks(blocksFromLayout(layout))).catch(() => {});
  };

  const handleDeleteVersion = (name) => {
    deleteVersion(name)
      .then(() => fetchLayouts())
      .then((l) => setVersions(l.versions || []))
      .catch(() => {});
  };

  // Bold technical keywords + metrics in a block WITHOUT rewriting it.
  const handleHighlight = (block) => {
    setHighlightingKey(block.key);
    highlightBullets(activeBulletsOf(block))
      .then((bulls) => {
        if (!bulls || !bulls.length) return;
        updateBlock(block.key, (b) => {
          const variants = [...b.variants, { label: "Highlighted", bullets: bulls }];
          return { ...b, variants, active: variants.length - 1 };
        });
      })
      .catch(() => {})
      .finally(() => setHighlightingKey(null));
  };

  // Opt-in segments (default:false in the manifest) offered in the "+ add" pickers,
  // minus any already present in the editor.
  const addableByKind = (kind) => {
    const present = new Set(blocks.map((b) => b.segment_id).filter(Boolean));
    return (suggestion.segments || []).filter(
      (s) => s.kind === kind && s.default === false && !present.has(s.id)
    );
  };

  // Merge the user's saved library blocks in once, so they're available on every
  // job. Skip any whose (kind+title) already appears among the suggested blocks.
  useEffect(() => {
    if (standalone) return undefined;  // keep a saved version faithful — no auto-appended library blocks
    let cancelled = false;
    savedBlocks()
      .then((res) => {
        if (cancelled) return;
        setBlocks((prev) => {
          const present = new Set(prev.map((b) => `${b.kind}::${b.title}`));
          const extra = (res.blocks || [])
            .filter((b) => KIND_ORDER.includes(b.kind) && !present.has(`${b.kind}::${b.title}`))
            .map((b) => ({
              key: `saved-${b.id}`, kind: b.kind, title: b.title,
              segment_id: null, source: "saved", active: 0,
              variants: [{ label: "Saved", bullets: b.bullets || [] }],
            }));
          return extra.length ? [...prev, ...extra] : prev;
        });
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const handleSaveToLibrary = (block) => {
    saveBlock({ kind: block.kind, title: block.title, bullets: activeBulletsOf(block) })
      .then(() => setSavedKeys((prev) => new Set(prev).add(block.key)))
      .catch(() => {});
  };

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
    setEditDetails("");
    setGenFailed(false);
  };

  // Rough notes -> 3 grounded bullets via the local LLM. Only numbers the
  // user typed survive (server-side grounding); fills the bullets box, which
  // the user can still tweak before Save. Never throws into the UI.
  const handleGenerateBullets = () => {
    if (!editDetails.trim()) return;
    setGenBusy(true);
    setGenFailed(false);
    const body = { heading: editTitle, details: editDetails };
    if (bulletCount !== "auto") body.n = Number(bulletCount);
    generateBullets(body)
      .then((bullets) => {
        if (bullets.length === 0) {
          setGenFailed(true);
          return;
        }
        setEditBullets(bullets.join("\n"));
      })
      .catch(() => setGenFailed(true))
      .finally(() => setGenBusy(false));
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
    setEditDetails("");
    setAddMenuKind(null);
  };

  // Add an opt-in library segment (e.g. a tailored skill group) as a block.
  const addSegmentBlock = (seg) => {
    setBlocks((prev) => (prev.some((b) => b.segment_id === seg.id) ? prev : [...prev, segToBlock(seg)]));
    setAddMenuKind(null);
  };

  // The candidate's own experience + project text — the grounding source for
  // every skill suggestion (server keeps only terms that literally appear here).
  const experienceText = () =>
    blocks
      .filter((b) => (b.kind === "experience" || b.kind === "project") && !b.excluded)
      .flatMap((b) => activeBulletsOf(b))
      .join("\n");

  // The individual skills already listed in a group's block (bold label stripped).
  const skillsInBlock = (block) =>
    activeBulletsOf(block).join(", ").replace(/\*\*[^*]+\*\*:?/g, "")
      .split(",").map((s) => s.trim()).filter(Boolean);

  // Suggest skills that fit THIS group's category (its heading), drawn from the
  // candidate's experience/projects and not already in the group.
  const handleSuggestForBlock = (block) => {
    setBlockSkillBusy(block.key);
    suggestSkills({ context: experienceText(), existing: skillsInBlock(block), category: block.title })
      .then((skills) => setBlockSkillSug((prev) => ({ ...prev, [block.key]: skills })))
      .catch(() => setBlockSkillSug((prev) => ({ ...prev, [block.key]: [] })))
      .finally(() => setBlockSkillBusy(null));
  };

  // Append a suggested skill into that specific group's skill line.
  const addSkillToBlock = (block, skill) => {
    setBlockSkillSug((prev) => ({ ...prev, [block.key]: (prev[block.key] || []).filter((s) => s !== skill) }));
    updateBlock(block.key, (b) => {
      const bullets = [...activeBulletsOf(b)];
      if (bullets.length === 0) bullets.push(skill);
      else bullets[0] = bullets[0] ? `${bullets[0]}, ${skill}` : skill;
      const variants = b.variants.map((v, i) => (i === b.active ? { ...v, bullets } : v));
      return { ...b, variants };
    });
  };

  // Ask the LLM for skills the candidate evidenced in their own experience +
  // projects but hasn't listed. Grounded server-side (never invents).
  const handleSuggestSkills = () => {
    setSkillSugBusy(true);
    setSkillSugDone(false);
    const contextText = blocks
      .filter((b) => (b.kind === "experience" || b.kind === "project") && !b.excluded)
      .flatMap((b) => activeBulletsOf(b))
      .join("\n");
    const existing = blocks
      .filter((b) => b.kind === "skills")
      .flatMap((b) => activeBulletsOf(b))
      .join(", ");
    suggestSkills({ context: contextText, existing: existing ? [existing] : [] })
      .then((skills) => setSkillSug(skills))
      .catch(() => setSkillSug([]))
      .finally(() => { setSkillSugBusy(false); setSkillSugDone(true); });
  };

  // Drop a suggested skill into an "Additional Skills" block (created on demand).
  const addSuggestedSkill = (skill) => {
    setSkillSug((prev) => prev.filter((s) => s !== skill));
    setBlocks((prev) => {
      const idx = prev.findIndex((b) => b.kind === "skills" && b.title === "Additional Skills");
      if (idx >= 0) {
        const b = prev[idx];
        const bullets = [...activeBulletsOf(b)];
        bullets[0] = bullets[0] ? `${bullets[0]}, ${skill}` : `**Additional**: ${skill}`;
        const copy = [...prev];
        copy[idx] = { ...b, variants: [{ label: "Original", bullets }], active: 0 };
        return copy;
      }
      customBlockCounter += 1;
      return [...prev, {
        key: `custom-skills-${customBlockCounter}`, kind: "skills", title: "Additional Skills",
        segment_id: null, source: "custom", active: 0, excluded: false,
        variants: [{ label: "Original", bullets: [`**Additional**: ${skill}`] }],
      }];
    });
  };

  const toggleExcluded = (key) =>
    updateBlock(key, (b) => ({ ...b, excluded: !b.excluded }));

  // Group experience blocks into companies (by `group`), preserving order.
  const companiesOf = (items) => {
    const order = [], map = {};
    items.forEach((b) => {
      const g = b.group || "Experience";
      if (!map[g]) { map[g] = []; order.push(g); }
      map[g].push(b);
    });
    return order.map((name) => ({ name, blocks: map[name] }));
  };

  // "+ add company" — a new employer with its own role/date header block.
  const addCompany = () => {
    customBlockCounter += 1;
    const key = `custom-exp-role-${customBlockCounter}`;
    const co = `New company ${customBlockCounter}`;
    setBlocks((prev) => [...prev, {
      key, kind: "experience", title: "", segment_id: null, source: "custom",
      active: 0, excluded: false, group: co, roleHeader: true,
      variants: [{ label: "Original", bullets: [] }],
    }]);
    setEditingKey(key); setEditTitle(""); setEditBullets(""); setEditDetails(""); setGenFailed(false);
  };

  // "+ add role/project under <company>" — a sub-project under the SAME employer,
  // inserted right after that company's existing blocks.
  const addRoleUnder = (company) => {
    customBlockCounter += 1;
    const key = `custom-exp-${customBlockCounter}`;
    const nb = {
      key, kind: "experience", title: "", segment_id: null, source: "custom",
      active: 0, excluded: false, group: company, roleHeader: false,
      variants: [{ label: "Original", bullets: [] }],
    };
    setBlocks((prev) => {
      let lastIdx = -1;
      prev.forEach((b, i) => { if (b.kind === "experience" && (b.group || "Experience") === company) lastIdx = i; });
      const copy = [...prev];
      copy.splice(lastIdx >= 0 ? lastIdx + 1 : prev.length, 0, nb);
      return copy;
    });
    setEditingKey(key); setEditTitle(""); setEditBullets(""); setEditDetails(""); setGenFailed(false);
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
        .filter((b) => b.kind === kind && !b.excluded)
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
    if (standalone) {
      // Flush the current blocks to this version, then let the parent open its
      // freshly-rendered PDF (job-agnostic — no JD, no highlight).
      saveLayout(layoutFromBlocks(blocks))
        .then(() => onGenerate(autoSaveName))
        .catch(() => onGenerate(autoSaveName));
      return;
    }
    onGenerate(buildLayout());
  };

  const groups = KIND_ORDER.map((kind) => ({
    kind,
    label: KIND_LABELS[kind],
    items: blocks.filter((b) => b.kind === kind),
  }));

  // One editable block card. Reused by the flat lists (skills/projects) and,
  // for experience, nested inside each company card.
  const renderBlock = (block) => (
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
        opacity: block.excluded ? 0.45 : 1,
      }}
    >
      {editingKey === block.key ? (
        <div>
          <input
            aria-label="Block title"
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            placeholder={block.roleHeader ? "Role, Company — Dates (e.g. Data Scientist, Tata AIG — July 2023 – Present)" : block.kind === "experience" ? "Sub-project heading (e.g. Health Fraud Pipeline)" : "Heading"}
            style={{ width: "100%", fontSize: 12, marginBottom: 6, padding: 6, boxSizing: "border-box" }}
          />
          {!block.roleHeader && (
            <>
              <textarea
                aria-label="Details for AI"
                value={editDetails}
                onChange={(e) => setEditDetails(e.target.value)}
                placeholder="Details — rough notes, tech stack, any numbers. AI writes 3 bullets from this (keeps only numbers you type)."
                rows={3}
                style={{ width: "100%", fontSize: 12, padding: 6, boxSizing: "border-box", background: "var(--canvas)" }}
              />
              <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "6px 0" }}>
                <button
                  onClick={handleGenerateBullets}
                  disabled={genBusy || !editDetails.trim()}
                  style={{ ...SMALL_BTN, background: "var(--green-tint)", color: "var(--green)", opacity: !editDetails.trim() ? 0.5 : 1 }}
                >
                  {genBusy ? "Writing…" : "✨ Generate bullets"}
                </button>
                <select
                  value={bulletCount}
                  onChange={(e) => setBulletCount(e.target.value)}
                  aria-label="How many bullets"
                  title="Auto = one bullet per note (nothing dropped). Pick a number to consolidate down."
                  style={{ fontSize: 11, padding: "3px 6px", border: "0.5px solid var(--hairline)", borderRadius: 6 }}
                >
                  <option value="auto">auto</option>
                  <option value="3">3 bullets</option>
                  <option value="4">4 bullets</option>
                  <option value="5">5 bullets</option>
                </select>
                {genFailed && (
                  <span style={{ fontSize: 11, color: "var(--ink-faint)", fontStyle: "italic" }}>
                    couldn't generate — type bullets below
                  </span>
                )}
              </div>
              <textarea
                aria-label="Block bullets"
                value={editBullets}
                onChange={(e) => setEditBullets(e.target.value)}
                placeholder="One bullet per line (or use Generate above)"
                rows={4}
                style={{ width: "100%", fontSize: 12, padding: 6, boxSizing: "border-box" }}
              />
            </>
          )}
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
            <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
              <input
                type="checkbox"
                checked={!block.excluded}
                onChange={() => toggleExcluded(block.key)}
                aria-label={`Include ${block.title || "block"} in resume`}
                title={block.excluded ? "Excluded from the résumé — check to include" : "Included — uncheck to leave out"}
                style={{ flexShrink: 0, cursor: "pointer", accentColor: "var(--green)" }}
              />
              <span title="Drag to reorder" aria-hidden="true"
                style={{ cursor: "grab", color: "var(--ink-faint)", fontSize: 13, flexShrink: 0, userSelect: "none" }}>
                ⠿
              </span>
              <div style={{ fontSize: 13, fontWeight: block.roleHeader ? 600 : 500, color: "var(--ink)", textDecoration: block.excluded ? "line-through" : "none" }}>
                {block.title || "(untitled)"}
              </div>
            </div>
            <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
              {!block.roleHeader && (
                <>
                  <button
                    onClick={() => handleHighlight(block)}
                    disabled={highlightingKey === block.key}
                    title="Bold the technical keywords + impact numbers, keeping your wording"
                    style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--green)" }}
                  >
                    {highlightingKey === block.key ? "Highlighting…" : "Highlight"}
                  </button>
                  {jobId && (
                    <button
                      onClick={() => handleRegenerate(block)}
                      disabled={regeneratingKey === block.key}
                      title="Rewrite into punchy alternatives (grounded — keeps your numbers)"
                      style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--ink)" }}
                    >
                      {regeneratingKey === block.key ? "Rewriting…" : "Rewrite"}
                    </button>
                  )}
                </>
              )}
              {block.kind === "skills" && (
                <button
                  onClick={() => handleSuggestForBlock(block)}
                  disabled={blockSkillBusy === block.key}
                  title={`Suggest skills from your experience that fit "${block.title || "this group"}"`}
                  style={{ ...SMALL_BTN, background: "var(--green-tint)", color: "var(--green)" }}
                >
                  {blockSkillBusy === block.key ? "Scanning…" : "✨ Suggest"}
                </button>
              )}
              <button onClick={() => startEdit(block)} style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--ink)" }}>
                Edit
              </button>
              {!block.roleHeader && (
                <button onClick={() => handleSaveToLibrary(block)}
                  title="Save this block to your reusable library — it'll appear on every future résumé"
                  style={{ ...SMALL_BTN, background: "var(--canvas)", color: savedKeys.has(block.key) ? "var(--green)" : "var(--ink-faint)" }}>
                  {savedKeys.has(block.key) ? "✓ In library" : "Save to library"}
                </button>
              )}
              <button onClick={() => deleteBlock(block.key)} style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--dupe-ink)" }}>
                Delete
              </button>
            </div>
          </div>

          {activeBulletsOf(block).length > 0 && (
            <ul style={{ margin: "6px 0 0", paddingLeft: 16, fontSize: 12, color: "var(--ink-soft)" }}>
              {activeBulletsOf(block).map((bullet, i) => (
                <li key={i}>{renderBulletText(bullet)}</li>
              ))}
            </ul>
          )}

          {block.kind === "skills" && blockSkillSug[block.key] && (
            blockSkillSug[block.key].length > 0 ? (
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 11, color: "var(--ink-faint)", marginBottom: 4 }}>
                  From your experience — click to add to “{block.title || "this group"}”:
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {blockSkillSug[block.key].map((s) => (
                    <button key={s} onClick={() => addSkillToBlock(block, s)}
                      style={{ ...SMALL_BTN, border: "0.5px solid var(--hairline)", background: "var(--green-tint)", color: "var(--green)" }}>
                      + {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div style={{ fontSize: 11, color: "var(--ink-faint)", fontStyle: "italic", marginTop: 8 }}>
                No unlisted skills found for this group.
              </div>
            )
          )}

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
  );

  return (
    <div style={{ marginTop: 12, borderTop: "0.5px solid var(--hairline)", paddingTop: 12 }}>
      {layoutError && (
        <div style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{layoutError}</div>
      )}

      {/* Versions — edits auto-save; save named variants and switch between them. */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
        <span style={{ fontSize: 11, color: "var(--ink-faint)" }}>Version:</span>
        {versions.length > 0 && (
          <>
            <select
              aria-label="Load résumé version"
              onChange={(e) => { handleLoadVersion(e.target.value); e.target.value = ""; }}
              defaultValue=""
              style={{ fontSize: 11, padding: "3px 6px" }}
            >
              <option value="" disabled>Load a version…</option>
              {versions.map((v) => (
                <option key={v.name} value={v.name}>{v.name}</option>
              ))}
            </select>
            {versions.map((v) => (
              <button key={`del-${v.name}`} onClick={() => handleDeleteVersion(v.name)}
                title={`Delete version "${v.name}"`}
                style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--ink-faint)" }}>
                ✕ {v.name}
              </button>
            ))}
          </>
        )}
        <input
          aria-label="New version name"
          value={versionName}
          onChange={(e) => setVersionName(e.target.value)}
          placeholder="Name this version"
          style={{ fontSize: 11, padding: "3px 6px", width: 130 }}
        />
        <button onClick={handleSaveVersion} disabled={!versionName.trim()}
          style={{ ...SMALL_BTN, background: "var(--green-tint)", color: "var(--green)", opacity: versionName.trim() ? 1 : 0.5 }}>
          Save version
        </button>
        <span style={{ fontSize: 10, color: "var(--ink-faint)", fontStyle: "italic" }}>edits auto-save</span>
      </div>

      {groups.map((group) => (
        <div key={group.kind} style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)" }}>{group.label}</div>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              {group.kind === "skills" && (
                <button
                  onClick={handleSuggestSkills}
                  disabled={skillSugBusy}
                  title="Suggest skills you used in your experience/projects but didn't list"
                  style={{ ...SMALL_BTN, background: "var(--green-tint)", color: "var(--green)" }}
                >
                  {skillSugBusy ? "Scanning…" : "✨ Suggest skills"}
                </button>
              )}
              <button
                onClick={() =>
                  group.kind === "experience"
                    ? addCompany()
                    : group.kind === "skills" && addableByKind("skills").length
                      ? setAddMenuKind(addMenuKind === group.kind ? null : group.kind)
                      : addBlock(group.kind)
                }
                style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--green)" }}
              >
                {ADD_LABELS[group.kind]}
                {group.kind === "skills" && addableByKind("skills").length ? " ▾" : ""}
              </button>
            </div>
          </div>

          {addMenuKind === group.kind && (
            <div style={{ border: "0.5px solid var(--hairline)", borderRadius: 8, padding: 6, marginBottom: 8, background: "var(--card)" }}>
              {addableByKind(group.kind).map((seg) => (
                <button key={seg.id} onClick={() => addSegmentBlock(seg)}
                  style={{ ...SMALL_BTN, display: "block", width: "100%", textAlign: "left", background: "var(--canvas)", color: "var(--ink)", marginBottom: 4 }}>
                  + {seg.title}
                </button>
              ))}
              <button onClick={() => addBlock(group.kind)}
                style={{ ...SMALL_BTN, display: "block", width: "100%", textAlign: "left", background: "var(--canvas)", color: "var(--ink-faint)" }}>
                + Blank skill group
              </button>
            </div>
          )}

          {group.kind === "skills" && (skillSug.length > 0 || skillSugDone) && (
            <div style={{ marginBottom: 8 }}>
              {skillSug.length > 0 ? (
                <>
                  <div style={{ fontSize: 11, color: "var(--ink-faint)", marginBottom: 4 }}>
                    From your experience/projects — click to add:
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {skillSug.map((s) => (
                      <button key={s} onClick={() => addSuggestedSkill(s)}
                        style={{ ...SMALL_BTN, border: "0.5px solid var(--hairline)", background: "var(--green-tint)", color: "var(--green)" }}>
                        + {s}
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <div style={{ fontSize: 11, color: "var(--ink-faint)", fontStyle: "italic" }}>
                  No unlisted skills found in your experience/projects.
                </div>
              )}
            </div>
          )}

          {group.items.length === 0 && (
            <div style={{ fontSize: 11, color: "var(--ink-faint)", fontStyle: "italic" }}>No blocks</div>
          )}

          {group.kind === "experience"
            ? companiesOf(group.items).map((co) => {
                const header = co.blocks.find((b) => b.roleHeader);
                const items = co.blocks.filter((b) => !b.roleHeader);
                return (
                  <div key={co.name} style={{ marginBottom: 14 }}>
                    {/* Role/company SUB-HEADING — a bold heading line (not a card).
                        A role can ALSO carry its own bullets (e.g. an internship
                        with no sub-projects) — those render right under the heading. */}
                    {header && editingKey === header.key ? (
                      <div style={{ marginBottom: 8 }}>
                        <input
                          aria-label="Role heading"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          placeholder="Role, Company — Dates (e.g. Data Scientist, Tata AIG — July 2023 – Present)"
                          style={{ width: "100%", fontSize: 13, fontWeight: 600, padding: 6, boxSizing: "border-box", marginBottom: 6 }}
                        />
                        <textarea
                          aria-label="Details for AI"
                          value={editDetails}
                          onChange={(e) => setEditDetails(e.target.value)}
                          placeholder="Details — rough notes. AI writes bullets (for a role with direct bullets, e.g. an internship)."
                          rows={2}
                          style={{ width: "100%", fontSize: 12, padding: 6, boxSizing: "border-box", background: "var(--canvas)" }}
                        />
                        <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "6px 0" }}>
                          <button onClick={handleGenerateBullets} disabled={genBusy || !editDetails.trim()}
                            style={{ ...SMALL_BTN, background: "var(--green-tint)", color: "var(--green)", opacity: !editDetails.trim() ? 0.5 : 1 }}>
                            {genBusy ? "Writing…" : "✨ Generate bullets"}
                          </button>
                        </div>
                        <textarea
                          aria-label="Block bullets"
                          value={editBullets}
                          onChange={(e) => setEditBullets(e.target.value)}
                          placeholder="Bullets for this role (leave empty if it only has sub-projects below)"
                          rows={3}
                          style={{ width: "100%", fontSize: 12, padding: 6, boxSizing: "border-box" }}
                        />
                        <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                          <button onClick={() => saveEdit(header)} style={{ ...SMALL_BTN, background: "var(--green)", color: "#FFFFFF" }}>Save</button>
                          <button onClick={() => cancelEdit(header)} style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--ink-faint)" }}>Cancel</button>
                        </div>
                      </div>
                    ) : header ? (
                      <div style={{ marginBottom: 8 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, borderBottom: "1px solid var(--hairline)", paddingBottom: 4 }}>
                          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--ink)" }}>{header.title || co.name}</div>
                          <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                            {activeBulletsOf(header).length > 0 && (
                              <button onClick={() => handleHighlight(header)} disabled={highlightingKey === header.key}
                                title="Bold the technical keywords + impact numbers"
                                style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--green)" }}>
                                {highlightingKey === header.key ? "Highlighting…" : "Highlight"}
                              </button>
                            )}
                            <button onClick={() => startEdit(header)} style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--ink)" }}>Edit</button>
                            <button onClick={() => deleteBlock(header.key)} style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--dupe-ink)" }}>Delete</button>
                          </div>
                        </div>
                        {activeBulletsOf(header).length > 0 && (
                          <ul style={{ margin: "6px 0 0", paddingLeft: 16, fontSize: 12, color: "var(--ink-soft)" }}>
                            {activeBulletsOf(header).map((b, i) => <li key={i}>{renderBulletText(b)}</li>)}
                          </ul>
                        )}
                      </div>
                    ) : (
                      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--ink)", borderBottom: "1px solid var(--hairline)", paddingBottom: 4, marginBottom: 8 }}>{co.name}</div>
                    )}
                    {/* Sub-projects — cards indented beneath the heading */}
                    <div style={{ marginLeft: 14 }}>
                      {items.map(renderBlock)}
                      <button onClick={() => addRoleUnder(co.name)}
                        style={{ ...SMALL_BTN, background: "var(--canvas)", color: "var(--green)", marginTop: 2 }}>
                        + add project under {co.name}
                      </button>
                    </div>
                  </div>
                );
              })
            : group.items.map(renderBlock)}
        </div>
      ))}

      {/* Live preview */}
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 6 }}>Preview</div>
        <div style={{ background: "var(--canvas)", border: "0.5px solid var(--hairline)", borderRadius: 10, padding: 10 }}>
          {blocks.length === 0 && (
            <div style={{ fontSize: 11, color: "var(--ink-faint)", fontStyle: "italic" }}>No blocks selected</div>
          )}
          {KIND_ORDER.flatMap((kind) => blocks.filter((b) => b.kind === kind && !b.excluded)).map((block) => (
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
          {generating ? "Generating…" : standalone ? "Save & open PDF ↗" : "Generate tailored resume"}
        </button>
        <button onClick={onCancel} style={{ ...BTN, background: "var(--canvas)", color: "var(--ink-faint)" }}>
          Cancel
        </button>
      </div>
    </div>
  );
}
