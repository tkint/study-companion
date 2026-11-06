import { Fragment, type ReactNode } from "react";
import styled from "styled-components";

// A small Markdown renderer for Claude's notes and questions: headings, paragraphs, lists
// (nested by indentation), quotes, code, tables, bold/italic/code/links. It builds React
// elements (never innerHTML), so text from the connector can't inject markup. Links open
// only for http(s) URLs.

type Block =
  | { t: "h"; level: number; text: string }
  | { t: "p"; text: string }
  | { t: "list"; ordered: boolean; items: { depth: number; text: string }[] }
  | { t: "quote"; text: string }
  | { t: "code"; text: string }
  | { t: "table"; head: string[]; rows: string[][] }
  | { t: "hr" };

const LIST = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

function cells(line: string): string[] {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

export function parse(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (/^\s*```/.test(line)) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push({ t: "code", text: body.join("\n") });
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      out.push({ t: "h", level: h[1].length, text: h[2].replace(/\s#+\s*$/, "") });
      i++;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      out.push({ t: "hr" });
      i++;
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push({ t: "table", head, rows });
      continue;
    }
    if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push({ t: "quote", text: body.join("\n") });
      continue;
    }
    const li = LIST.exec(line);
    if (li) {
      const ordered = /\d/.test(li[2]);
      const items: { depth: number; text: string }[] = [];
      while (i < lines.length) {
        const m = LIST.exec(lines[i]);
        if (m) {
          items.push({ depth: Math.min(3, Math.floor(m[1].replace(/\t/g, "  ").length / 2)), text: m[3] });
          i++;
        } else if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length) {
          items[items.length - 1].text += " " + lines[i++].trim(); // continuation line
        } else break;
      }
      out.push({ t: "list", ordered, items });
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !LIST.exec(lines[i]) && !/^(#{1,6})\s/.test(lines[i])
      && !/^\s*(```|>)/.test(lines[i])) {
      para.push(lines[i++].trim());
    }
    out.push({ t: "p", text: para.join("\n") });
  }
  return out;
}

const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*|__[^_]+__)|(\*[^*\s][^*]*\*|_[^_\s][^_]*_)|(\[[^\]]+\]\([^)\s]+\))/;

export function inline(text: string, key = 0): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text;
  let k = key;
  while (rest) {
    const m = INLINE.exec(rest);
    if (!m) {
      out.push(...lineBreaks(rest, k++));
      break;
    }
    if (m.index > 0) out.push(...lineBreaks(rest.slice(0, m.index), k++));
    const tok = m[0];
    if (m[1]) out.push(<code key={k++}>{tok.slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={k++}>{inline(tok.slice(2, -2), k * 100)}</strong>);
    else if (m[3]) out.push(<em key={k++}>{inline(tok.slice(1, -1), k * 100)}</em>);
    else {
      const [, label, url] = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok) ?? [];
      out.push(/^https?:\/\//i.test(url ?? "")
        ? <a key={k++} href={url} target="_blank" rel="noopener noreferrer">{label}</a>
        : <Fragment key={k++}>{label}</Fragment>);
    }
    rest = rest.slice(m.index + tok.length);
  }
  return out;
}

function lineBreaks(text: string, key: number): ReactNode[] {
  return text.split("\n").flatMap((part, i) => (i ? [<br key={`${key}-${i}`} />, part] : [part]));
}

const Body = styled.div`
  font-size: ${({ theme }) => theme.fontSizes.md};
  overflow-wrap: anywhere;
  & > :first-child { margin-top: 6px; }
  p, ul, ol, blockquote, pre { margin: 6px 0; }
  ul, ol { padding-left: 1.3em; }
  li { margin: 2px 0; }
  h3, h4, h5, h6 { font-size: 1rem; margin: 14px 0 4px; }
  h4, h5, h6 { font-size: .95rem; }
  code {
    font-size: .88em;
    padding: 1px 5px;
    border-radius: 4px;
    background: ${({ theme }) => theme.colors.surfaceSunken};
  }
  pre {
    overflow-x: auto;
    padding: 10px 12px;
    border-radius: ${({ theme }) => theme.radii.sm};
    background: ${({ theme }) => theme.colors.surfaceSunken};
    code { padding: 0; background: none; }
  }
  blockquote {
    padding-left: 12px;
    border-left: 3px solid ${({ theme }) => theme.colors.accent};
    color: ${({ theme }) => theme.colors.textMuted};
  }
  hr { border: 0; border-top: 1px solid ${({ theme }) => theme.colors.border}; }
  table { border-collapse: collapse; font-size: ${({ theme }) => theme.fontSizes.sm}; min-width: 100%; }
  th, td { border: 1px solid ${({ theme }) => theme.colors.border}; padding: 4px 8px; text-align: left; vertical-align: top; }
  th { background: ${({ theme }) => theme.colors.surfaceSunken}; }
`;

const TableWrap = styled.div`
  overflow-x: auto;
  margin: 6px 0;
`;

export function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <Body className={className}>
      {parse(text).map((b, i) => {
        switch (b.t) {
          case "h": {
            const level = Math.min(6, b.level + 2); // h3+ inside a page section
            const Tag = `h${level}` as "h3";
            return <Tag key={i}>{inline(b.text)}</Tag>;
          }
          case "p":
            return <p key={i}>{inline(b.text)}</p>;
          case "quote":
            return <blockquote key={i}>{inline(b.text)}</blockquote>;
          case "code":
            return <pre key={i}><code>{b.text}</code></pre>;
          case "hr":
            return <hr key={i} />;
          case "table":
            return (
              <TableWrap key={i}>
                <table>
                  <thead><tr>{b.head.map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead>
                  <tbody>
                    {b.rows.map((r, j) => (
                      <tr key={j}>{r.map((c, n) => <td key={n}>{inline(c)}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            );
          case "list": {
            const Tag = b.ordered ? "ol" : "ul";
            return (
              <Tag key={i}>
                {b.items.map((it, j) => (
                  <li key={j} style={it.depth ? { marginLeft: `${it.depth * 1.2}em` } : undefined}>
                    {inline(it.text)}
                  </li>
                ))}
              </Tag>
            );
          }
        }
      })}
    </Body>
  );
}
