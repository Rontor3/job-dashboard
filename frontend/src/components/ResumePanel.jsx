import React, { useState } from "react";
import { fetchSegments, suggestResume, generateResume } from "../api.js";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px", borderRadius: "var(--radius-pill)", transition: "transform var(--dur-quick) ease-out" };

export default function ResumePanel({ jobId }) {
  const [stage, setStage] = useState("idle"); // idle, suggesting, suggested, generating, generated
  const [error, setError] = useState(null);
  const [suggestion, setSuggestion] = useState(null);
  const [checkedBlocks, setCheckedBlocks] = useState(new Set());
  const [acceptedRephrasings, setAcceptedRephrasings] = useState(new Set());
  const [generated, setGenerated] = useState(null);

  const handleSuggest = () => {
    setStage("suggesting");
    setError(null);
    Promise.all([suggestResume(jobId), fetchSegments()])
      .then(([sugg, segments]) => {
        setSuggestion({ ...sugg, segments });
        setCheckedBlocks(new Set(sugg.block_ids || []));
        setAcceptedRephrasings(new Set());
        setStage("suggested");
      })
      .catch((e) => {
        setError(String(e));
        setStage("idle");
      });
  };

  const handleGenerate = () => {
    if (checkedBlocks.size === 0) {
      setError("Select at least one block");
      return;
    }
    setStage("generating");
    setError(null);
    generateResume(jobId, Array.from(checkedBlocks), Array.from(acceptedRephrasings))
      .then((result) => {
        setGenerated(result);
        setStage("generated");
      })
      .catch((e) => {
        setError(String(e));
        setStage("suggested");
      });
  };

  const toggleBlock = (blockId) => {
    const updated = new Set(checkedBlocks);
    if (updated.has(blockId)) {
      updated.delete(blockId);
    } else {
      updated.add(blockId);
    }
    setCheckedBlocks(updated);
  };

  const toggleRephrasing = (rephrasing) => {
    const updated = new Set(acceptedRephrasings);
    if (updated.has(rephrasing)) {
      updated.delete(rephrasing);
    } else {
      updated.add(rephrasing);
    }
    setAcceptedRephrasings(updated);
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
        Analyzing job description…
      </div>
    );
  }

  if (stage === "suggested" && suggestion) {
    const segmentMap = {};
    if (suggestion.segments) {
      suggestion.segments.forEach((seg) => {
        segmentMap[seg.id] = seg;
      });
    }

    return (
      <div style={{ marginTop: 12, borderTop: "0.5px solid var(--hairline)", paddingTop: 12 }}>
        {error && (
          <div style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{error}</div>
        )}

        {/* Blocks */}
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 6 }}>
            Resume blocks
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {suggestion.block_ids &&
              suggestion.block_ids.map((blockId) => {
                const checkboxId = `block-${blockId}`;
                const title = segmentMap[blockId]?.title || blockId;
                return (
                  <label
                    key={blockId}
                    htmlFor={checkboxId}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "6px 10px",
                      background: "var(--green-tint)",
                      borderRadius: "var(--radius-tag)",
                      cursor: "pointer",
                      fontSize: 12,
                    }}
                  >
                    <input
                      id={checkboxId}
                      type="checkbox"
                      checked={checkedBlocks.has(blockId)}
                      onChange={() => toggleBlock(blockId)}
                      style={{ cursor: "pointer" }}
                    />
                    <span style={{ color: "var(--green)" }}>{title}</span>
                  </label>
                );
              })}
          </div>
        </div>

        {/* Rephrasings */}
        {suggestion.rephrasings && suggestion.rephrasings.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 6 }}>
              Keyword suggestions
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {suggestion.rephrasings.map((rep, idx) => {
                const repId = `rep-${idx}`;
                const isTransferable = rep.confidence === "transferable";
                return (
                  <div key={repId} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                    <input
                      type="checkbox"
                      checked={acceptedRephrasings.has(rep)}
                      onChange={() => toggleRephrasing(rep)}
                      style={{ marginTop: 4, cursor: "pointer" }}
                    />
                    <div style={{ flex: 1, fontSize: 12 }}>
                      <div style={{ color: "var(--ink-soft)" }}>
                        Could read as:{" "}
                        <span style={{ textDecoration: "line-through", color: "var(--ink-faint)" }}>
                          {rep.original_text}
                        </span>{" "}
                        → <span style={{ fontWeight: 500, color: "var(--ink)" }}>{rep.proposed_text}</span>
                      </div>
                      <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center" }}>
                        <span
                          style={{
                            fontSize: 10,
                            background:
                              rep.confidence === "exact-synonym"
                                ? "var(--green-tint)"
                                : rep.confidence === "equivalent"
                                  ? "var(--warm-tint)"
                                  : "var(--green-tint)",
                            color:
                              rep.confidence === "exact-synonym"
                                ? "var(--green)"
                                : rep.confidence === "equivalent"
                                  ? "var(--warm-ink)"
                                  : "var(--green)",
                            borderRadius: "var(--radius-pill)",
                            padding: "2px 8px",
                          }}
                        >
                          {rep.confidence}
                        </span>
                        {isTransferable && (
                          <span
                            style={{
                              fontSize: 10,
                              color: "var(--warm-ink)",
                              fontStyle: "italic",
                            }}
                          >
                            verify in interview
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Gaps */}
        {suggestion.gaps && suggestion.gaps.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 6 }}>
              Gaps
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {suggestion.gaps.map((gap) => (
                <span
                  key={gap.jd_keyword}
                  style={{
                    fontSize: 11,
                    background: "var(--warm-tint)",
                    color: "var(--warm-ink)",
                    borderRadius: "var(--radius-pill)",
                    padding: "4px 10px",
                  }}
                >
                  JD wants {gap.jd_keyword} — no match
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Generate button */}
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={handleGenerate}
            style={{
              ...BTN,
              background: "var(--green)",
              color: "#FFFFFF",
            }}
            disabled={stage === "generating"}
          >
            {stage === "generating" ? "Generating…" : "Generate tailored resume"}
          </button>
          <button
            onClick={() => setStage("idle")}
            style={{
              ...BTN,
              background: "var(--canvas)",
              color: "var(--ink-faint)",
            }}
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  if (stage === "generated" && generated) {
    return (
      <div style={{ marginTop: 12, borderTop: "0.5px solid var(--hairline)", paddingTop: 12 }}>
        {error && (
          <div style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{error}</div>
        )}

        {/* PDF link */}
        {generated.pdf_url && (
          <div style={{ marginBottom: 14 }}>
            <a
              href={generated.pdf_url}
              target="_blank"
              rel="noreferrer"
              style={{
                display: "inline-block",
                fontSize: 12,
                color: "var(--green)",
                textDecoration: "none",
                padding: "6px 12px",
                background: "var(--green-tint)",
                borderRadius: "var(--radius-pill)",
                fontWeight: 500,
              }}
            >
              Download tailored resume (PDF)
            </a>
          </div>
        )}

        {/* ATS score */}
        {generated.ats_report && (
          <div
            style={{
              background: "var(--green-tint)",
              borderRadius: 12,
              padding: "12px 14px",
              marginBottom: 14,
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--green)", marginBottom: 4 }}>
              ATS Score
            </div>
            <div style={{ fontSize: 24, fontWeight: 500, color: "var(--green)" }}>
              {generated.ats_report.ats_score}%
            </div>
            {generated.ats_report.missing_keywords && generated.ats_report.missing_keywords.length > 0 && (
              <div style={{ fontSize: 11, color: "var(--green-mid)", marginTop: 6 }}>
                <div style={{ fontWeight: 500, marginBottom: 4 }}>Missing keywords:</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {generated.ats_report.missing_keywords.map((kw, idx) => (
                    <span
                      key={idx}
                      style={{
                        background: "#F0F8F5",
                        color: "var(--green-mid)",
                        borderRadius: "var(--radius-tag)",
                        padding: "2px 8px",
                      }}
                    >
                      {kw}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Interview prep */}
        {generated.interview_prep && generated.interview_prep.length > 0 && (
          <div
            style={{
              background: "var(--warm-tint)",
              borderRadius: 12,
              padding: "12px 14px",
              marginBottom: 14,
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--warm-ink)", marginBottom: 6 }}>
              Interview prep
            </div>
            <ul
              style={{
                margin: 0,
                paddingLeft: 16,
                fontSize: 12,
                color: "var(--warm-ink)",
                lineHeight: 1.6,
              }}
            >
              {generated.interview_prep.map((prep, idx) => (
                <li key={idx}>
                  {prep.jd_keyword}: {prep.proposed_text}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Back button */}
        <button
          onClick={() => setStage("idle")}
          style={{
            ...BTN,
            background: "var(--canvas)",
            color: "var(--ink-faint)",
          }}
        >
          Start over
        </button>
      </div>
    );
  }

  return null;
}
