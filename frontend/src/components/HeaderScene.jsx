import React from "react";

export default function HeaderScene() {
  return (
    <svg viewBox="0 0 800 90" preserveAspectRatio="none" aria-hidden="true"
         style={{ position: "absolute", left: 0, bottom: 0, width: "100%", height: 70, pointerEvents: "none" }}>
      <path d="M0,90 L0,55 Q120,20 240,50 T480,45 T800,55 L800,90 Z" fill="var(--peach)" />
      <path d="M0,90 L0,70 Q200,40 400,68 T800,72 L800,90 Z" fill="var(--peach-deep)" />
      <path d="M540,58 L560,18 L584,58 Z" fill="#8A7BA8" opacity="0.85" />
      <path d="M600,62 L618,30 L638,62 Z" fill="#6E5F94" opacity="0.8" />
      <circle cx="700" cy="22" r="10" fill="#FFFFFF" opacity="0.9" />
    </svg>
  );
}
