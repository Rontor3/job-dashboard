// What a cursor click (or a "What does this mean?" link) hands the agent about an element: its semantic anchor if
// it sits inside one (`data-agent="<kind>:<id>"`), and always its visible text, label and nearest heading.
import type { ElementContext } from "@jobdash/agent-protocol";

const MAX_TEXT = 1500;
const squash = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim();

/** The element a click captures: the anchored component around it, else the nearest block. */
export function captureTarget(el: Element): Element {
  return el.closest("[data-agent]") ?? el.closest("article, li, section, tr, label, button, p, h1, h2, h3") ?? el;
}

function labelOf(el: Element): string | undefined {
  const own = el.getAttribute("aria-label");
  if (own) return own;
  const field = el.closest("label") ?? (el.id ? el.ownerDocument.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null);
  return squash(field?.textContent) || undefined;
}

function headingOf(el: Element): string | undefined {
  for (let node: Element | null = el; node; node = node.parentElement) {
    if (/^H[1-4]$/.test(node.tagName)) return squash(node.textContent);
    const h = node.querySelector("h1, h2, h3, h4, [role=heading]");
    if (h) return squash(h.textContent);
  }
  return undefined;
}

export function captureContext(clicked: Element, tab?: string): ElementContext {
  const target = captureTarget(clicked);
  const text = squash((target as HTMLElement).innerText ?? target.textContent).slice(0, MAX_TEXT);
  const ctx: ElementContext = { text };
  const anchor = target.getAttribute("data-agent");
  if (anchor) ctx.anchor = anchor;
  const label = labelOf(clicked);
  if (label && label !== text) ctx.label = label;
  const heading = headingOf(target);
  if (heading && heading !== text) ctx.heading = heading;
  if (tab) ctx.tab = tab;
  return ctx;
}
