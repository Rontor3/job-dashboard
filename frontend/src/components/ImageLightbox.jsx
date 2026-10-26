import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

// A thumbnail that opens its image in an overlay with a visible Close, Esc and backdrop-click to dismiss.
// Tall (full-page) screenshots scroll inside the overlay. The overlay is portalled to <body>: inside a transformed card
// "position: fixed" is fixed to the card, and focusing its Close button scrolled the page back to the top.
// `gallery` ([{src, alt}]) + `index` make it one viewer for a whole set: ‹ › buttons and the arrow keys step through
// it, so a run's page screenshots no longer need closing one to open the next.
const NAV = { position: "fixed", top: "50%", transform: "translateY(-50%)", border: "none", cursor: "pointer",
              fontSize: 22, lineHeight: 1, width: 44, height: 44, borderRadius: 999, background: "#fff", color: "#111" };

export default function ImageLightbox({ src, thumbSrc, alt, thumbStyle, gallery, index = 0 }) {
  const items = gallery && gallery.length ? gallery : [{ src, alt }];
  const [at, setAt] = useState(null);            // null = closed, else the open item's position in `items`
  const closeRef = useRef(null);
  const boxRef = useRef(null);
  const open = at !== null;
  const many = items.length > 1;
  const go = (step) => setAt((i) => (i + step + items.length) % items.length);

  useEffect(() => {
    if (!open) return undefined;
    if (closeRef.current) closeRef.current.focus({ preventScroll: true });
    const onKey = (e) => {
      if (e.key === "Escape") setAt(null);
      else if (many && e.key === "ArrowRight") go(1);
      else if (many && e.key === "ArrowLeft") go(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, many]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (boxRef.current) boxRef.current.scrollTop = 0; }, [at]);   // each page starts at its top

  const cur = open ? items[at] : null;
  const stop = (fn) => (e) => { e.stopPropagation(); fn(); };
  return (
    <>
      <button type="button" onClick={() => setAt(Math.min(index, items.length - 1))} aria-label={`Open ${alt}`}
              style={{ border: "none", background: "none", padding: 0, cursor: "zoom-in", display: "block" }}>
        <img src={thumbSrc || src} alt={alt} style={thumbStyle} />
      </button>
      {open && createPortal(
        <div role="dialog" aria-modal="true" aria-label={cur.alt} onClick={() => setAt(null)} ref={boxRef}
             style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.78)", overflow: "auto", padding: "56px 64px 24px" }}>
          <div style={{ position: "fixed", top: 12, right: 16, display: "flex", gap: 8, alignItems: "center" }}>
            {many && (
              <span data-testid="lightbox-count" style={{ color: "#fff", fontSize: 13 }}>
                {at + 1} / {items.length}
              </span>
            )}
            <button type="button" onClick={stop(() => setAt(null))} aria-label="Close image" ref={closeRef}
                    style={{ border: "none", cursor: "pointer", fontSize: 13, padding: "8px 14px", borderRadius: 999,
                             background: "#fff", color: "#111" }}>
              ✕ Close
            </button>
          </div>
          {many && (
            <>
              <button type="button" aria-label="Previous screenshot" onClick={stop(() => go(-1))} style={{ ...NAV, left: 12 }}>‹</button>
              <button type="button" aria-label="Next screenshot" onClick={stop(() => go(1))} style={{ ...NAV, right: 12 }}>›</button>
            </>
          )}
          <img src={cur.src} alt={cur.alt} onClick={(e) => e.stopPropagation()}
               style={{ display: "block", margin: "0 auto", maxWidth: "100%", borderRadius: 6 }} />
        </div>,
        document.body,
      )}
    </>
  );
}
