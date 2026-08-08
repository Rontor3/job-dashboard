// Job descriptions arrive in two messy shapes depending on the source board:
//  1. HTML (Naukri, some Indeed): "<p><strong>Skills</strong></p><br />…"
//  2. escaped markdown: punctuation backslash-escaped ("cutting\-edge") and
//     bold markers ("**About Us**").
// Rendered as plain text (the detail panel uses white-space: pre-wrap) both show
// their raw tags/escapes. Convert to clean, readable text without pulling in a
// markdown/HTML renderer. Tags are stripped (not rendered) so there's no XSS
// surface.
export function cleanJd(text) {
  if (!text) return "";
  let s = String(text).replace(/\r\n/g, "\n");

  if (/<\/?[a-z][\s\S]*?>/i.test(s)) {
    s = s
      .replace(/<\s*(?:br|hr)\s*\/?>/gi, "\n")
      .replace(/<\s*li[^>]*>/gi, "\n• ")
      .replace(/<\s*\/\s*(?:p|div|li|ul|ol|h[1-6]|tr|table|section)\s*>/gi, "\n")
      .replace(/<[^>]+>/g, "") // strip any remaining tags
      .replace(/&nbsp;/gi, " ")
      .replace(/&amp;/gi, "&")
      .replace(/&lt;/gi, "<")
      .replace(/&gt;/gi, ">")
      .replace(/&quot;/gi, '"')
      .replace(/&#(\d+);/g, (_, n) => {
        try { return String.fromCharCode(Number(n)); } catch { return " "; }
      })
      .replace(/&[a-z]+;/gi, " "); // any other named entity -> space
  }

  return s
    .replace(/\\([-+*.()\[\]\/#!_>~])/g, "$1") // drop escaping backslashes
    .replace(/\*\*(.+?)\*\*/g, "$1") // **bold** -> bold
    .replace(/[ \t]+\n/g, "\n") // trailing spaces
    .replace(/\n{3,}/g, "\n\n") // collapse blank-line runs
    .trim();
}
