// Job descriptions often arrive as escaped markdown from the source boards:
// punctuation is backslash-escaped ("cutting\-edge", "R1013045\)",
// "Machine Learning\/Deep") and headings use bold markers ("**About Us**").
// Rendered as plain text those escapes/markers show literally. Clean them so
// the JD reads naturally without pulling in a full markdown renderer.
export function cleanJd(text) {
  if (!text) return "";
  return String(text)
    .replace(/\r\n/g, "\n")
    .replace(/\\([-+*.()\[\]\/#!_>~])/g, "$1") // drop escaping backslashes
    .replace(/\*\*(.+?)\*\*/g, "$1") // **bold** -> bold
    .replace(/\n{3,}/g, "\n\n"); // collapse runs of blank lines
}
