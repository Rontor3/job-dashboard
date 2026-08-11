import React, { useState } from "react";
import { fetchSegments, suggestResume, generateResume, fetchLayouts } from "../api.js";
import BlockEditor from "./BlockEditor.jsx";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px", borderRadius: "var(--radius-pill)", transition: "transform var(--dur-quick) ease-out" };

export default function ResumePanel({ jobId }) {
  const [stage, setStage] = useState("idle"); // idle, suggesting, suggested
  const [error, setError] = useState(null);
  const [suggestion, setSuggestion] = useState(null);
  const [generated, setGenerated] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [jdInfo, setJdInfo] = useState(null); // {gaps} after an explicit "Tailor to this JD"
  const [jdBusy, setJdBusy] = useState(false);

  // Opening the editor NO LONGER scans the JD (no LLM). It just loads the
  // segment library + the saved working résumé + named versions. JD tailoring
  // is opt-in via handleTailorToJd below.
  const handleSuggest = () => {
    setStage("suggesting");
    setError(null);
    Promise.all([fetchSegments(), fetchLayouts()])
      .then(([segments, layouts]) => {
        setSuggestion({
          segments,
          working: layouts.working || null,
          versions: layouts.versions || [],
        });
        setStage("suggested");
      })
      .catch((e) => {
        setError(String(e));
        setStage("idle");
      });
  };

  // Explicit, on-demand JD analysis (the only place the JD-keyword LLM runs).
  const handleTailorToJd = () => {
    setJdBusy(true);
    suggestResume(jobId)
      .then((sugg) => setJdInfo({ gaps: sugg.gaps || [] }))
      .catch(() => setJdInfo({ gaps: [] }))
      .finally(() => setJdBusy(false));
  };

  const handleGenerateLayout = (layout) => {
    setGenerating(true);
    setError(null);
    // Stay on the editor stage so BlockEditor stays mounted (its block edits,
    // exclusions and order are preserved). The rendered draft appears above it,
    // and the user can keep adding/removing/editing then re-render.
    generateResume(jobId, [], [], layout)
      .then((result) => setGenerated(result))
      .catch((e) => setError(String(e)))
      .finally(() => setGenerating(false));
  };

  if (stage === "idle") {
    return (
      <div style={{ marginTop: 12 }}>
        <button
          onClick={handleSuggest}
          style={{ ...BTN, background: "var(--green)", color: "#FFFFFF" }}
        >
          Tailor resume
        </button>
      </div>
    );
  }

  if (stage === "suggesting") {
    return (
      <div style={{ marginTop: 12, color: "var(--ink-soft)", fontSize: 12 }}>
        Loading your résumé…
      </div>
    );
  }

  if (stage === "suggested" && suggestion) {
    const ats = generated && generated.ats_report;
    return (
      <div>
        {error && (
          <div style={{ color: "var(--dupe-ink)", fontSize: 12, marginTop: 12 }}>{error}</div>
        )}

        {/* JD tailoring is opt-in — nothing scans the JD until you click here. */}
        <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={handleTailorToJd}
            disabled={jdBusy}
            style={{ ...BTN, fontSize: 11, padding: "4px 12px", background: "var(--canvas)", color: "var(--green)", border: "0.5px solid var(--hairline)" }}
          >
            {jdBusy ? "Reading JD…" : "Tailor to this JD"}
          </button>
          {jdInfo && (
            jdInfo.gaps.length > 0 ? (
              <span style={{ fontSize: 11, color: "var(--ink-soft)" }}>
                JD gaps to address: {jdInfo.gaps.map((g) => (g.jd_keyword || g)).join(", ")}
              </span>
            ) : (
              <span style={{ fontSize: 11, color: "var(--ink-faint)", fontStyle: "italic" }}>
                No obvious JD gaps.
              </span>
            )
          )}
        </div>

        {generated && (
          <div style={{ marginTop: 12, background: "var(--green-tint)", borderRadius: 12, padding: "12px 14px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <div style={{ fontSize: 12, fontWeight: 500, color: "var(--green)" }}>
                Tailored draft ready{ats ? ` · ATS ${ats.ats_score}%` : ""}
              </div>
              {generated.pdf_url && (
                <a href={generated.pdf_url} target="_blank" rel="noreferrer"
                  style={{ fontSize: 12, color: "var(--green)", textDecoration: "none", padding: "4px 12px", background: "#FFFFFF", borderRadius: "var(--radius-pill)", fontWeight: 500 }}>
                  Open PDF ↗
                </a>
              )}
            </div>
            {ats && ats.missing_keywords && ats.missing_keywords.length > 0 && (
              <div style={{ fontSize: 11, color: "var(--green-mid)", marginTop: 6 }}>
                Missing keywords: {ats.missing_keywords.join(", ")}
              </div>
            )}
            <div style={{ fontSize: 11, color: "var(--green-mid)", marginTop: 6, fontStyle: "italic" }}>
              Add, remove (uncheck) or edit blocks below, then re-render.
            </div>
          </div>
        )}

        <BlockEditor
          jobId={jobId}
          suggestion={suggestion}
          generating={generating}
          hasDraft={!!generated}
          onGenerate={handleGenerateLayout}
          onCancel={() => { setStage("idle"); setGenerated(null); }}
        />
      </div>
    );
  }

  return null;
}

