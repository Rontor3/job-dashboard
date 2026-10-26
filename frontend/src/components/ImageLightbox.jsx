import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

// A thumbnail that opens its image in an overlay with a visible Close, Esc and backdrop-click to dismiss.
// Tall (full-page) screenshots scroll inside the overlay. The overlay is portalled to <body>: inside a transformed card
// "position: fixed" is fixed to the card, and focusing its Close button scrolled the page back to the top.
export default function ImageLightbox({ src, thumbSrc, alt, thumbStyle }) {
  const [open, setOpen] = useState(false);
  const closeRef = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    if (closeRef.current) closeRef.current.focus({ preventScroll: true });
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} aria-label={`Open ${alt}`}
              style={{ border: "none", background: "none", padding: 0, cursor: "zoom-in", display: "block" }}>
        <img src={thumbSrc || src} alt={alt} style={thumbStyle} />
      </button>
      {open && createPortal(
        <div role="dialog" aria-modal="true" aria-label={alt} onClick={() => setOpen(false)}
             style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.78)", overflow: "auto", padding: "56px 16px 24px" }}>
          <button type="button" onClick={() => setOpen(false)} aria-label="Close image" ref={closeRef}
                  style={{ position: "fixed", top: 12, right: 16, border: "none", cursor: "pointer", fontSize: 13,
                           padding: "8px 14px", borderRadius: 999, background: "#fff", color: "#111" }}>
            ✕ Close
          </button>
          <img src={src} alt={alt} onClick={(e) => e.stopPropagation()}
               style={{ display: "block", margin: "0 auto", maxWidth: "100%", borderRadius: 6 }} />
        </div>,
        document.body,
      )}
    </>
  );
}
