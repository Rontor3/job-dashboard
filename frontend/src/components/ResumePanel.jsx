import React, { useState } from "react";
import { fetchSegments, suggestResume, generateResume } from "../api.js";
import BlockEditor from "./BlockEditor.jsx";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px", borderRadius: "var(--radius-pill)", transition: "transform var(--dur-quick) ease-out" };

export default function ResumePanel({ jobId }) {
  const [stage, setStage] = useState("idle"); // idle, suggesting, suggested, generating, generated
  const [error, setError] = useState(null);
  const [suggestion, setSuggestion] = useState(null);
  const [generated, setGenerated] = useState(null);

  const handleSuggest = () => {
    setStage("suggesting");
    setError(null);
    Promise.all([suggestResume(jobId), fetchSegments()])
      .then(([sugg, segments]) => {
        setSuggestion({ ...sugg, segments });
        setStage("suggested");
      })
      .catch((e) => {
        setError(String(e));
        setStage("idle");
      });
  };

  const handleGenerateLayout = (layout) => {
    setStage("generating");
    setError(null);
    generateResume(jobId, [], [], layout)
      .then((result) => {
        setGenerated(result);
        setStage("generated");
      })
      .catch((e) => {
        setError(String(e));
        setStage("suggested");
      });
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

  if ((stage === "suggested" || stage === "generating") && suggestion) {
    return (
      <div>
        {error && (
          <div style={{ color: "var(--dupe-ink)", fontSize: 12, marginTop: 12 }}>{error}</div>
        )}
        <BlockEditor
          jobId={jobId}
          suggestion={suggestion}
          generating={stage === "generating"}
          onGenerate={handleGenerateLayout}
          onCancel={() => setStage("idle")}
        />
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
