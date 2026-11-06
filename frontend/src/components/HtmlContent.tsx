import { createElement, type ReactNode } from "react";
import styled from "styled-components";

// Renders a teacher page (HTML already sanitised by the server) as React elements, with a
// second allow-list here: unknown tags keep only their text, attributes are rebuilt from
// scratch, and only in-app or http(s)/mailto links and same-origin or https images survive.
// DOMParser documents are inert (no scripts run, nothing loads), and nothing goes through
// innerHTML.

const TAGS = new Set([
  "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd",
  "strong", "b", "em", "i", "u", "s", "strike", "del", "ins", "sub", "sup", "small", "mark",
  "blockquote", "pre", "code", "kbd", "samp", "abbr", "cite", "q",
  "table", "caption", "thead", "tbody", "tfoot", "tr", "th", "td",
  "a", "img", "figure", "figcaption", "div", "span", "section", "article", "details", "summary",
]);
const VOID = new Set(["br", "hr", "img"]);
// Page headings sit under the viewer's own title.
const HEADING: Record<string, string> = { h1: "h2", h2: "h3", h3: "h3", h4: "h4", h5: "h5", h6: "h6" };
// React warns about whitespace text directly inside these.
const TABLE_PARTS = new Set(["table", "thead", "tbody", "tfoot", "tr"]);

const Body = styled.div`
  line-height: 1.6;
  overflow-wrap: anywhere;
  h2, h3, h4, h5, h6 { font-weight: 700; line-height: 1.3; }
  h2 { font-size: ${({ theme }) => theme.fontSizes.lg}; margin: 20px 0 8px; }
  h3 { font-size: 1.05rem; margin: 18px 0 6px; }
  h4, h5, h6 { font-size: ${({ theme }) => theme.fontSizes.base}; margin: 14px 0 4px; }
  p, ul, ol, blockquote, pre, figure, dl { margin: 8px 0; }
  ul, ol { padding-left: 1.4em; }
  ul { list-style: disc; }
  ol { list-style: decimal; }
  li { margin: 2px 0; }
  strong, b { font-weight: 700; }
  em, i { font-style: italic; }
  u { text-decoration: underline; }
  a { color: ${({ theme }) => theme.colors.primaryStrong}; text-decoration: underline; }
  img { max-width: 100%; height: auto; border-radius: ${({ theme }) => theme.radii.sm}; display: inline-block; }
  blockquote {
    margin-left: 0;
    padding: 2px 0 2px 12px;
    border-left: 3px solid ${({ theme }) => theme.colors.accent};
    color: ${({ theme }) => theme.colors.textMuted};
  }
  code {
    font-family: ${({ theme }) => theme.fonts.mono};
    font-size: .9em;
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
  hr { border: 0; border-top: 1px solid ${({ theme }) => theme.colors.border}; margin: 16px 0; }
`;

const TableWrap = styled.div`
  overflow-x: auto;
  margin: 10px 0;
  -webkit-overflow-scrolling: touch;
  table { border-collapse: collapse; min-width: 100%; font-size: ${({ theme }) => theme.fontSizes.md}; }
  th, td {
    border: 1px solid ${({ theme }) => theme.colors.border};
    padding: 6px 8px;
    text-align: left;
    vertical-align: top;
    overflow-wrap: normal;
  }
  th { background: ${({ theme }) => theme.colors.surfaceSunken}; }
`;

function safeHref(href: string): { href: string; external: boolean } | null {
  if (/^#\/file\/\d+(\?course=\d+)?$/.test(href)) return { href, external: false };
  if (/^\/files\/\d+\/[^?#]*$/.test(href)) return { href, external: false };
  if (/^(https?:\/\/|mailto:)/i.test(href)) return { href, external: true };
  return null;
}

function safeSrc(src: string): string | null {
  if (/^\/files\/\d+\/[^?#]*$/.test(src)) return src;
  if (/^https:\/\//i.test(src)) return src;
  return null;
}

function convert(node: Node, key: number, parentTag = ""): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) {
    const text = node.textContent ?? "";
    if (TABLE_PARTS.has(parentTag) && !text.trim()) return null;
    return text;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return null;
  const el = node as Element;
  const tag = el.tagName.toLowerCase();
  const kids = () => Array.from(el.childNodes).map((c, i) => convert(c, i, tag));
  if (!TAGS.has(tag)) return <span key={key}>{kids()}</span>;

  const props: Record<string, unknown> = { key };
  if (tag === "a") {
    const link = safeHref(el.getAttribute("href") ?? "");
    if (!link) return <span key={key}>{kids()}</span>;
    props.href = link.href;
    if (link.external) {
      props.target = "_blank";
      props.rel = "noopener noreferrer";
    }
  } else if (tag === "img") {
    const src = safeSrc(el.getAttribute("src") ?? "");
    if (!src) return null;
    props.src = src;
    props.alt = el.getAttribute("alt") ?? "";
    props.loading = "lazy";
    props.referrerPolicy = "no-referrer";
  } else if (tag === "td" || tag === "th") {
    for (const name of ["colspan", "rowspan"] as const) {
      const v = el.getAttribute(name);
      if (v && /^\d{1,3}$/.test(v)) props[name === "colspan" ? "colSpan" : "rowSpan"] = Number(v);
    }
  } else if (tag === "ol") {
    const start = el.getAttribute("start");
    if (start && /^\d{1,5}$/.test(start)) props.start = Number(start);
  }
  const title = el.getAttribute("title");
  if (title && (tag === "abbr" || tag === "a" || tag === "img")) props.title = title;

  const name = HEADING[tag] ?? tag;
  if (VOID.has(tag)) return createElement(name, props);
  if (tag === "table") {
    return (
      <TableWrap key={key}>
        {createElement("table", null, kids())}
      </TableWrap>
    );
  }
  return createElement(name, props, kids());
}

export function HtmlContent({ html }: { html: string }) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  return <Body>{Array.from(doc.body.childNodes).map((n, i) => convert(n, i))}</Body>;
}
