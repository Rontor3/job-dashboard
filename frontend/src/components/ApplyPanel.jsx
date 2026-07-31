import React, { useEffect, useState } from "react";
import { fetchApplicationPackage, fetchApplication, saveApplication } from "../api.js";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px", borderRadius: "var(--radius-pill)", transition: "transform var(--dur-quick) ease-out" };

const SAFETY_TEXT =
  "The agent fills the form in your Chrome and stops at Submit — you review and send it. It never submits, logs in, or solves CAPTCHAs.";

function SafetyBanner() {
  return (
    <div
      style={{
        fontSize: 12,
        color: "var(--ink-soft)",
        background: "var(--canvas)",
        border: "0.5px solid var(--hairline)",
        borderRadius: 10,
        padding: "10px 12px",
        marginBottom: 14,
      }}
    >
      {SAFETY_TEXT}
    </div>
  );
}

export default function ApplyPanel({ jobId }) {
  // loading, ready, preparing, prepared, marking, applied
  const [stage, setStage] = useState("loading");
  const [error, setError] = useState(null);
  const [pkg, setPkg] = useState(null);
  const [includeCoverLetter, setIncludeCoverLetter] = useState(false);
  const [application, setApplication] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setStage("loading");
    setError(null);
    Promise.all([fetchApplicationPackage(jobId), fetchApplication(jobId)])
      .then(([p, app]) => {
        if (cancelled) return;
        setPkg(p || {});
        setIncludeCoverLetter(false);
        if (app && app.status === "applied") {
          setApplication(app);
          setStage("applied");
        } else if (app && app.status === "prepared") {
          setApplication(app);
          setStage("prepared");
        } else {
          setStage("ready");
        }
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
        setStage("ready");
        setPkg({});
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const handlePrepare = () => {
    setStage("preparing");
    setError(null);
    const coverLetter = pkg && pkg.cover_letter;
    saveApplication(jobId, {
      status: "prepared",
      cover_letter_id: includeCoverLetter && coverLetter ? coverLetter.id : null,
      ats: pkg && pkg.ats_hint,
    })
      .then((result) => {
        setApplication(result);
        setStage("prepared");
      })
      .catch((e) => {
        setError(String(e));
        setStage("ready");
      });
  };

  const handleMarkApplied = () => {
    setStage("marking");
    setError(null);
    const coverLetter = pkg && pkg.cover_letter;
    saveApplication(jobId, {
      status: "applied",
      cover_letter_id: includeCoverLetter && coverLetter ? coverLetter.id : null,
      ats: pkg && pkg.ats_hint,
    })
      .then((result) => {
        setApplication(result);
        setStage("applied");
      })
      .catch((e) => {
        setError(String(e));
        setStage("prepared");
      });
  };

  if (stage === "loading") {
    return (
      <div style={{ marginTop: 12, color: "var(--ink-soft)", fontSize: 12 }}>
        Loading application package…
      </div>
    );
  }

  if ((stage === "ready" || stage === "preparing") && pkg) {
    const profile = pkg.profile;
    const hasProfile = profile && (profile.name || profile.email);
    const resume = pkg.resume;
    const coverLetter = pkg.cover_letter;

    return (
      <div style={{ marginTop: 12, borderTop: "0.5px solid var(--hairline)", paddingTop: 12 }}>
        {error && (
          <div style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{error}</div>
        )}

        <SafetyBanner />

        <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 6 }}>
          Application profile
        </div>
        {hasProfile ? (
          <div style={{ fontSize: 12, color: "var(--ink-soft)", marginBottom: 14 }}>
            {profile.name || "—"} · {profile.email || "—"}
          </div>
        ) : (
          <div style={{ fontSize: 12, color: "var(--ink-faint)", fontStyle: "italic", marginBottom: 14 }}>
            Set up your application profile to speed up autofill.
          </div>
        )}

        <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 6 }}>
          Resume
        </div>
        {resume ? (
          <div style={{ fontSize: 12, color: "var(--ink-soft)", marginBottom: 14 }}>
            {resume.filename || resume.title || `Resume #${resume.id}`}
          </div>
        ) : (
          <div style={{ fontSize: 12, color: "var(--ink-faint)", fontStyle: "italic", marginBottom: 14 }}>
            No tailored resume yet — generate one above.
          </div>
        )}

        {coverLetter && (
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 12,
              color: "var(--ink)",
              marginBottom: 14,
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={includeCoverLetter}
              onChange={(e) => setIncludeCoverLetter(e.target.checked)}
            />
            Attach cover letter (only if the form has a slot)
          </label>
        )}

        <button
          onClick={handlePrepare}
          disabled={stage === "preparing"}
          style={{ ...BTN, background: "var(--green)", color: "#FFFFFF" }}
        >
          {stage === "preparing" ? "Preparing…" : "Prepare application"}
        </button>
      </div>
    );
  }

  if (stage === "prepared" || stage === "marking") {
    const coverLetter = pkg && pkg.cover_letter;
    return (
      <div style={{ marginTop: 12, borderTop: "0.5px solid var(--hairline)", paddingTop: 12 }}>
        {error && (
          <div style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{error}</div>
        )}

        <SafetyBanner />

        <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 6 }}>
          Prepared
        </div>
        <ul style={{ margin: 0, marginBottom: 14, paddingLeft: 16, fontSize: 12, color: "var(--ink-soft)", lineHeight: 1.6 }}>
          <li>Resume attached</li>
          <li>{includeCoverLetter && coverLetter ? "Cover letter attached" : "No cover letter attached"}</li>
          <li>Ready for the browser agent to fill the form in your Chrome</li>
        </ul>

        <div style={{ fontSize: 12, color: "var(--ink-soft)", marginBottom: 14 }}>
          Start the browser agent to fill the application in your Chrome. It will stop at Submit for you to review and send.
        </div>

        <button
          onClick={handleMarkApplied}
          disabled={stage === "marking"}
          style={{ ...BTN, background: "var(--gold)", color: "var(--gold-ink)" }}
        >
          {stage === "marking" ? "Saving…" : "Mark as applied"}
        </button>
      </div>
    );
  }

  if (stage === "applied") {
    return (
      <div style={{ marginTop: 12, borderTop: "0.5px solid var(--hairline)", paddingTop: 12 }}>
        {error && (
          <div style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{error}</div>
        )}

        <SafetyBanner />

        <div
          style={{
            fontSize: 12,
            color: "var(--green)",
            background: "var(--green-tint)",
            borderRadius: 10,
            padding: "10px 12px",
          }}
        >
          Marked as applied.
        </div>
      </div>
    );
  }

  return null;
}
