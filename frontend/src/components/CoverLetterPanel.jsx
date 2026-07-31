import React, { useState } from "react";
import {
  draftCoverLetter,
  generateCoverLetter,
  gatherCompanyResources,
  selectCompanyResources,
} from "../api.js";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px", borderRadius: "var(--radius-pill)", transition: "transform var(--dur-quick) ease-out" };
const MAX_SELECTED = 2;

export default function CoverLetterPanel({ jobId }) {
  // idle, gathering, researched, drafting, drafted, generating, generated
  const [stage, setStage] = useState("idle");
  const [error, setError] = useState(null);
  const [draft, setDraft] = useState(null);
  const [body, setBody] = useState("");
  const [generated, setGenerated] = useState(null);
  const [resources, setResources] = useState([]);
  const [selectedUrls, setSelectedUrls] = useState([]);
  const [limitHint, setLimitHint] = useState(false);

  const handleGatherResearch = () => {
    setStage("gathering");
    setError(null);
    setLimitHint(false);
    gatherCompanyResources(jobId)
      .then((found) => {
        setResources(found);
        setSelectedUrls(found.filter((r) => r.selected).map((r) => r.source_url));
        setStage("researched");
      })
      .catch((e) => {
        setError(String(e));
        setStage("idle");
      });
  };

  const toggleResource = (sourceUrl) => {
    const isSelected = selectedUrls.includes(sourceUrl);
    if (!isSelected && selectedUrls.length >= MAX_SELECTED) {
      setLimitHint(true);
      return;
    }
    setLimitHint(false);
    const next = isSelected
      ? selectedUrls.filter((u) => u !== sourceUrl)
      : [...selectedUrls, sourceUrl];
    setSelectedUrls(next);
    selectCompanyResources(jobId, next).catch((e) => setError(String(e)));
  };

  const handleDraft = () => {
    setStage("drafting");
    setError(null);
    draftCoverLetter(jobId)
      .then((result) => {
        setDraft(result);
        setBody(result.body || "");
        setStage("drafted");
      })
      .catch((e) => {
        setError(String(e));
        setStage("idle");
      });
  };

  const handleGenerate = () => {
    setStage("generating");
    setError(null);
    generateCoverLetter(jobId, body)
      .then((result) => {
        setGenerated(result);
        setStage("generated");
      })
      .catch((e) => {
        setError(String(e));
        setStage("drafted");
      });
  };

  if (stage === "idle") {
    return (
      <div style={{ marginTop: 12 }}>
        {error && (
          <div style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{error}</div>
        )}
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={handleGatherResearch}
            style={{ ...BTN, background: "var(--canvas)", color: "var(--green)", border: "0.5px solid var(--hairline)" }}
          >
            Find company research
          </button>
          <button
            onClick={handleDraft}
            style={{ ...BTN, background: "var(--green)", color: "#FFFFFF" }}
          >
            Draft cover letter
          </button>
        </div>
      </div>
    );
  }

  if (stage === "gathering") {
    return (
      <div style={{ marginTop: 12, color: "var(--ink-soft)", fontSize: 12 }}>
        Finding company research…
      </div>
    );
  }

  if (stage === "researched") {
    return (
      <div style={{ marginTop: 12, borderTop: "0.5px solid var(--hairline)", paddingTop: 12 }}>
        {error && (
          <div style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{error}</div>
        )}

        <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 6 }}>
          Company research
        </div>

        {resources.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 8 }}>
            {resources.map((r) => (
              <label
                key={r.source_url}
                style={{
                  display: "flex",
                  gap: 8,
                  alignItems: "flex-start",
                  padding: 10,
                  background: "var(--card)",
                  border: "0.5px solid var(--hairline)",
                  borderRadius: "var(--radius-card)",
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={selectedUrls.includes(r.source_url)}
                  onChange={() => toggleResource(r.source_url)}
                  style={{ marginTop: 2 }}
                />
                <div>
                  <a
                    href={r.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ fontSize: 12, fontWeight: 500, color: "var(--green)" }}
                  >
                    {r.title}
                  </a>
                  <div style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 2 }}>
                    {r.summary}
                  </div>
                </div>
              </label>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: 12, color: "var(--ink-faint)", fontStyle: "italic", marginBottom: 8 }}>
            No company research found.
          </div>
        )}

        {limitHint && (
          <div style={{ fontSize: 11, color: "var(--ink-faint)", marginBottom: 8 }}>
            Pick up to 2 sources.
          </div>
        )}

        <button
          onClick={handleDraft}
          style={{ ...BTN, background: "var(--green)", color: "#FFFFFF" }}
        >
          Draft cover letter
        </button>
      </div>
    );
  }

  if (stage === "drafting") {
    return (
      <div style={{ marginTop: 12, color: "var(--ink-soft)", fontSize: 12 }}>
        Researching company…
      </div>
    );
  }

  if ((stage === "drafted" || stage === "generating") && draft) {
    const facts = draft.company_facts_used || [];
    const unsupportedClaims =
      (draft.grounding && draft.grounding.unsupported_company_claims) || [];

    return (
      <div style={{ marginTop: 12, borderTop: "0.5px solid var(--hairline)", paddingTop: 12 }}>
        {error && (
          <div style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{error}</div>
        )}

        {/* Company research */}
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 6 }}>
            Company research used
          </div>
          {facts.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {facts.map((fact, idx) => (
                <div key={idx} style={{ fontSize: 12, color: "var(--ink-soft)" }}>
                  {fact.text}{" "}
                  {fact.source_url && (
                    <a
                      href={fact.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: "var(--green)" }}
                    >
                      source
                    </a>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: "var(--ink-faint)", fontStyle: "italic" }}>
              No company-specific research found — letter kept general.
            </div>
          )}
        </div>

        {/* Unsupported claim flags */}
        {unsupportedClaims.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 14 }}>
            {unsupportedClaims.map((claim, idx) => (
              <span
                key={idx}
                style={{
                  fontSize: 11,
                  background: "var(--warm-tint)",
                  color: "var(--warm-ink)",
                  borderRadius: "var(--radius-pill)",
                  padding: "4px 10px",
                }}
              >
                Verify: {claim}
              </span>
            ))}
          </div>
        )}

        {/* Editable body */}
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 6 }}>
            Letter
          </div>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={12}
            style={{
              width: "100%",
              fontSize: 12,
              fontFamily: "inherit",
              color: "var(--ink)",
              background: "var(--canvas)",
              border: "0.5px solid var(--hairline)",
              borderRadius: 8,
              padding: 10,
              boxSizing: "border-box",
              resize: "vertical",
            }}
          />
        </div>

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
            {stage === "generating" ? "Generating…" : "Generate PDF"}
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

        {generated.pdf_url && (
          <div style={{ marginBottom: 14 }}>
            <a
              href={generated.pdf_url}
              target="_blank"
              rel="noopener noreferrer"
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
              Download cover letter
            </a>
          </div>
        )}

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
