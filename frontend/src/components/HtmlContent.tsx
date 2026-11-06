import { createElement, type ReactNode } from "react";

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
      <div key={key} className="page-table">
        {createElement("table", null, kids())}
      </div>
    );
  }
  return createElement(name, props, kids());
}

export function HtmlContent({ html }: { html: string }) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  return <div className="page-content">{Array.from(doc.body.childNodes).map((n, i) => convert(n, i))}</div>;
}
