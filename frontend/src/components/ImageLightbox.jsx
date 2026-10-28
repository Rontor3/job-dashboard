import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

// A thumbnail that opens its image in an overlay with a visible Close, Esc and backdrop-click to dismiss.
// Tall (full-page) screenshots scroll inside the overlay. The overlay is portalled to <body>: inside a transformed card
// "position: fixed" is fixed to the card, and focusing its Close button scrolled the page back to the top.
// `gallery` ([{src, alt, aside?, asideTitle?}]) + `index` make it one viewer for a whole set: ‹ › and the arrow keys
// step through it. An item's `aside` (the page's questions) sits beside its image, like comments beside a photo.
const PILL = { border: "none", cursor: "pointer", fontSize: 13, padding: "8px 14px", borderRadius: 999,
               background: "#fff", color: "#111" };

export default function ImageLightbox({ src, thumbSrc, alt, thumbStyle, gallery, index = 0 }) {
  const items = gallery && gallery.length ? gallery : [{ src, alt }];
  const [at, setAt] = useState(null);            // null = closed, else the open item's position in `items`
  const closeRef = useRef(null);
  const imgRef = useRef(null);
  const asideRef = useRef(null);
  const open = at !== null;
  const many = items.length > 1;
  const go = (step) => setAt((i) => (i + step + items.length) % items.length);

  useEffect(() => {
    if (!open) return undefined;
    if (closeRef.current) closeRef.current.focus({ preventScroll: true });
    const onKey = (e) => {
      if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;   // typing a corrected answer
      if (e.key === "Escape") setAt(null);
      else if (many && e.key === "ArrowRight") go(1);
      else if (many && e.key === "ArrowLeft") go(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, many]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {                               // each page starts at its top, image and questions alike
    if (imgRef.current) imgRef.current.scrollTop = 0;
    if (asideRef.current) asideRef.current.scrollTop = 0;
  }, [at]);

  const cur = open ? items[at] : null;
  const stop = (fn) => (e) => { e.stopPropagation(); fn(); };
  const keep = (e) => e.stopPropagation();
  return (
    <>
      <button type="button" onClick={() => setAt(Math.min(index, items.length - 1))} aria-label={`Open ${alt}`}
              style={{ border: "none", background: "none", padding: 0, cursor: "zoom-in", display: "block" }}>
        <img src={thumbSrc || src} alt={alt} style={thumbStyle} />
      </button>
      {open && createPortal(
        <div role="dialog" aria-modal="true" aria-label={cur.alt} onClick={() => setAt(null)}
             style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.78)",
                      display: "flex", flexWrap: "wrap", overflow: "auto" }}>
          <div style={{ position: "fixed", top: 12, right: 16, zIndex: 1, display: "flex", gap: 8, alignItems: "center" }}>
            {many && (
              <>
                <button type="button" aria-label="Previous screenshot" onClick={stop(() => go(-1))} style={PILL}>‹</button>
                <span data-testid="lightbox-count" style={{ color: "#fff", fontSize: 13, minWidth: 44, textAlign: "center" }}>
                  {at + 1} / {items.length}
                </span>
                <button type="button" aria-label="Next screenshot" onClick={stop(() => go(1))} style={PILL}>›</button>
              </>
            )}
            <button type="button" onClick={stop(() => setAt(null))} aria-label="Close image" ref={closeRef} style={PILL}>
              ✕ Close
            </button>
          </div>
          <div ref={imgRef} style={{ flex: "1 1 520px", minWidth: 0, maxHeight: cur.aside ? "100vh" : "none",
                                     overflow: "auto", padding: "60px 16px 24px" }}>
            <img src={cur.src} alt={cur.alt} onClick={keep}
                 style={{ display: "block", margin: "0 auto", maxWidth: "100%", borderRadius: 6 }} />
          </div>
          {cur.aside && (
            <aside ref={asideRef} aria-label={cur.asideTitle || "Details"} onClick={keep}
                   style={{ flex: "0 1 400px", minWidth: 0, maxHeight: "100vh", overflow: "auto", boxSizing: "border-box",
                            padding: "60px 16px 24px", background: "var(--canvas, #f6f5f1)", color: "var(--ink, #111)" }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{cur.asideTitle || "Details"}</div>
              {cur.aside}
            </aside>
          )}
        </div>,
        document.body,
      )}
    </>
  );
}
