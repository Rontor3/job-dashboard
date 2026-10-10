// The agent's markdown, rendered as pi's terminal renders it: headings, lists, quotes, fenced code, inline code,
// bold, italics and links. Built as React elements from the text, never as HTML, so a reply can't inject markup.
import { Fragment, type ReactNode } from "react";

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(\*[^*\s][^*\n]*\*)|(\[[^\]\n]+\]\((?:https?:\/\/|mailto:)[^)\s]+\))|(https?:\/\/[^\s)]+)/g;

export function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const t = m[0];
    const key = `${at}`;
    if (m[1]) out.push(<code key={key}>{t.slice(1, -1)}</code>);
    else if (m[2] || m[3]) out.push(<strong key={key}>{inline(t.slice(2, -2))}</strong>);
    else if (m[4]) out.push(<em key={key}>{inline(t.slice(1, -1))}</em>);
    else if (m[5]) {
      const [, label, href] = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(t)!;
      out.push(<a key={key} href={href} target="_blank" rel="noreferrer">{label}</a>);
    } else out.push(<a key={key} href={t} target="_blank" rel="noreferrer">{t}</a>);
    last = at + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Block =
  | { kind: "p" | "quote"; lines: string[] }
  | { kind: "h"; level: number; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "code"; lang: string; text: string }
  | { kind: "hr" }
  | { kind: "table"; rows: string[][] };

const STARTS_BLOCK = /^(#{1,6}\s|\s*(```|~~~)|\s*([-*+]|\d+[.)])\s|\s*\|.*\|\s*$)/;

export function blocks(src: string): Block[] {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const out: Block[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const fence = /^\s*(```|~~~)\s*(\S*)/.exec(line);
    if (fence) {
      const body: string[] = [];
      for (i++; i < lines.length && !lines[i]!.trim().startsWith(fence[1]!); i++) body.push(lines[i]!);
      out.push({ kind: "code", lang: fence[2] ?? "", text: body.join("\n") });
      continue;
    }
    if (!line.trim()) continue;
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) { out.push({ kind: "h", level: h[1]!.length, text: h[2]! }); continue; }
    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) { out.push({ kind: "hr" }); continue; }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const rows: string[][] = [];
      for (; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]!); i++) {
        if (/^\s*\|[\s:|-]+\|\s*$/.test(lines[i]!)) continue;                  // the |---|---| separator
        rows.push(lines[i]!.trim().slice(1, -1).split("|").map((c) => c.trim()));
      }
      i--;
      out.push({ kind: "table", rows });
      continue;
    }
    const list = /^\s*([-*+]|\d+[.)])\s+/.exec(line);
    if (list) {
      const ordered = /\d/.test(list[1]!);
      const items: string[] = [];
      for (; i < lines.length; i++) {
        const m = /^\s*([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i]!);
        if (m) items.push(m[2]!);
        else if (lines[i]!.trim() && /^\s{2,}/.test(lines[i]!) && items.length) items[items.length - 1] += ` ${lines[i]!.trim()}`;
        else break;
      }
      i--;
      out.push({ kind: ordered ? "ol" : "ul", items });
      continue;
    }
    const quote = line.startsWith(">");
    const para: string[] = [];
    for (; i < lines.length; i++) {
      const l = lines[i]!;
      if (!l.trim() || l.startsWith(">") !== quote || (para.length && STARTS_BLOCK.test(l))) break;
      para.push(quote ? l.replace(/^>\s?/, "") : l);
    }
    i--;
    out.push({ kind: quote ? "quote" : "p", lines: para });
  }
  return out;
}

const lines = (ls: string[]) => ls.map((l, i) => <Fragment key={i}>{i > 0 && <br />}{inline(l)}</Fragment>);

export default function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      {blocks(text).map((b, i) => {
        switch (b.kind) {
          case "h": return <div key={i} className={`md-h md-h${b.level}`}>{inline(b.text)}</div>;
          case "p": return <p key={i}>{lines(b.lines)}</p>;
          case "quote": return <blockquote key={i}>{lines(b.lines)}</blockquote>;
          case "ul": return <ul key={i}>{b.items.map((t, j) => <li key={j}>{inline(t)}</li>)}</ul>;
          case "ol": return <ol key={i}>{b.items.map((t, j) => <li key={j}>{inline(t)}</li>)}</ol>;
          case "code": return <pre key={i} data-lang={b.lang || undefined}><code>{b.text}</code></pre>;
          case "hr": return <hr key={i} />;
          case "table": return (
            <table key={i}><tbody>{b.rows.map((r, j) => (
              <tr key={j}>{r.map((c, k) => (j === 0 ? <th key={k}>{inline(c)}</th> : <td key={k}>{inline(c)}</td>))}</tr>
            ))}</tbody></table>
          );
          default: return null;
        }
      })}
    </div>
  );
}
