"""Teacher pages: the HTML that Moodle "page" and "book" activities export as ``index.html``.

Moodle shows these as web pages, so the app shows them too instead of offering a download.
``core_course_get_contents`` lists, for a page, ``index.html`` (filepath ``/``) plus the
images and attachments it uses; for a book, one ``index.html`` per chapter (filepath
``/<chapter id>/``) with that chapter's files next to it. Inside the HTML, references are
relative (``image.png``, Moodle strips ``@@PLUGINFILE@@/``), older sites leave
``@@PLUGINFILE@@/`` in, and some point at ``.../pluginfile.php/<ctx>/mod_page/content/...``.
All three are matched to the synced copies of those files.

The HTML goes through an allow-list: structure and text formatting only, no scripts, styles,
classes, event handlers, forms or frames (an embedded video becomes a link). The browser
then renders it into React elements with a second allow-list, never ``innerHTML``.
"""

from __future__ import annotations

import mimetypes
import posixpath
import re
from urllib.parse import quote, unquote, urlsplit

from sqlalchemy.engine import Engine
from sqlmodel import col, select

from app.db import session
from app.extract.formats import kind_of
from app.models import Course, File, FilePage, Module
from app.moodle.text import resolve_multilang

MAX_HTML_BYTES = 3 * 1024 * 1024
MAX_TITLE = 120
INDEX_NAMES = {"index.html", "index.htm"}

ALLOWED = {
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd",
    "strong", "b", "em", "i", "u", "s", "strike", "del", "ins", "sub", "sup", "small", "mark",
    "blockquote", "pre", "code", "kbd", "samp", "abbr", "cite", "q",
    "table", "caption", "thead", "tbody", "tfoot", "tr", "th", "td",
    "a", "img", "figure", "figcaption", "div", "span", "section", "article", "details", "summary",
}
# Removed with everything inside them.
DROP = {"script", "style", "noscript", "template", "head", "title", "meta", "link", "base",
        "form", "input", "button", "select", "textarea", "option", "object", "embed", "applet",
        "svg", "math", "canvas", "map", "frameset", "frame"}
# Replaced by a link to what they embed.
EMBEDS = {"iframe", "video", "audio", "source"}
ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "abbr": {"title"},
    "ol": {"start"},
}
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
VIEWABLE = {"pdf", "html"}  # opened in the app's viewer


def is_page(f: File) -> bool:
    """An HTML file the app shows as a page (any HTML, not only ``index.html``)."""
    return kind_of(f.mimetype, f.filename) == "html"


# ------------------------------------------------------------------------ titles


def titles(engine: Engine, files: list[File]) -> dict[int, str]:
    """A readable name for each teacher page among ``files`` (by file id): the activity name
    for a page, the chapter heading for a book chapter, else the file name. Other files are
    left out (their file name is fine)."""
    wanted = {f.id for f in files if f.id and _is_index(f)}
    if not wanted:
        return {}
    module_ids = list({f.module_id for f in files if f.id in wanted})
    with session(engine) as s:
        # All chapters of those modules, so a chapter's title doesn't depend on the caller.
        pages = [f for f in s.exec(
            select(File).where(col(File.module_id).in_(module_ids), File.status != "removed")
        ).all() if _is_index(f)]
    per_module: dict[int, list[File]] = {}
    for f in pages:
        per_module.setdefault(f.module_id, []).append(f)
    with session(engine) as s:
        names = {m.id: m.name for m in s.exec(
            select(Module).where(col(Module.id).in_(list(per_module)))
        ).all()}
        firsts = {p.file_id: p.text for p in s.exec(
            select(FilePage).where(col(FilePage.file_id).in_([f.id for f in pages]),
                                   FilePage.page == 1)
        ).all()}
    out: dict[int, str] = {}
    for module_id, group in per_module.items():
        name = names.get(module_id, "") or "Page"
        group.sort(key=lambda f: f.id or 0)
        for n, f in enumerate(group, start=1):
            if len(group) == 1:
                out[f.id] = name
                continue
            first = (firsts.get(f.id) or "").strip().split("\n", 1)[0].strip()
            out[f.id] = first[:MAX_TITLE] if first else f"{name}, chapter {n}"
    return {k: v for k, v in out.items() if k in wanted}


def _is_index(f: File) -> bool:
    return is_page(f) and f.filename.lower() in INDEX_NAMES


# ------------------------------------------------------------------------ rendering


def render(engine: Engine, data_dir, file_id: int) -> dict | None:
    """The page as sanitised HTML with its references resolved, or None if it isn't a
    synced HTML file."""
    from app.moodle.names import UnsafePathError, safe_join

    with session(engine) as s:
        f = s.get(File, file_id)
        if f is None or f.status != "ok" or not f.local_path or not is_page(f):
            return None
        module = s.get(Module, f.module_id)
        course = s.get(Course, f.course_id)
        siblings = s.exec(
            select(File).where(File.module_id == f.module_id, File.status != "removed")
            .order_by(File.id)
        ).all()
    try:
        path = safe_join(data_dir, f.local_path)
    except UnsafePathError:
        return None
    if not path.is_file():
        return None
    raw = path.read_bytes()[:MAX_HTML_BYTES]
    html = _decode(raw)
    lang = course.lang if course else ""
    resolver = _Resolver(engine, f, siblings, f.course_id)
    body, heading, used = sanitise(html, resolver, lang)

    chapters = [g for g in siblings if is_page(g) and g.status == "ok"]
    names = titles(engine, chapters)
    module_name = module.name if module else ""
    title = names.get(f.id) or heading or module_name or f.filename
    if heading and heading == title:
        body = _drop_first_heading(body)
    attachments = [
        {"id": g.id, "filename": g.filename, "href": resolver.link(g)}
        for g in siblings
        if g.id != f.id and g.id not in used and not is_page(g) and g.status == "ok"
        and _filepath_dir(g.filepath) == _filepath_dir(f.filepath)
    ]
    return {
        "id": f.id,
        "title": title,
        "module": {"id": module.id, "name": module_name, "modname": module.modname,
                   "url": module.url} if module else None,
        "course_id": f.course_id,
        "html": body,
        "chapters": [{"id": g.id, "title": names.get(g.id) or g.filename} for g in chapters]
        if len(chapters) > 1 else [],
        "attachments": attachments,
    }


def _drop_first_heading(body: str) -> str:
    """The viewer shows the title already; a book chapter starts with the same heading."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(body, "html.parser")
    first = soup.find(["h1", "h2", "h3", "h4"])
    if first is not None:
        first.decompose()
    return soup.decode().strip()


def _decode(raw: bytes) -> str:
    m = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', raw[:2048])
    encodings = [m.group(1).decode("ascii")] if m else []
    for enc in encodings + ["utf-8-sig", "cp1252", "latin-1"]:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _filepath_dir(filepath: str) -> str:
    p = "/" + (filepath or "/").strip("/")
    return p if p == "/" else p + "/"


class _Resolver:
    """Maps a reference found in a page to a URL inside the app (or None)."""

    def __init__(self, engine: Engine, page: File, siblings: list[File], course_id: int) -> None:
        self.engine = engine
        self.page = page
        self.course_id = course_id
        self.base = _filepath_dir(page.filepath)
        self.by_path = {(_filepath_dir(g.filepath), g.filename): g for g in siblings}
        self.by_name: dict[str, list[File]] = {}
        for g in siblings:
            self.by_name.setdefault(g.filename.lower(), []).append(g)
        self.by_url = {}
        for g in siblings:
            tail = _pluginfile_tail(g.fileurl)
            if tail:
                self.by_url[tail] = g
        self.used: set[int] = set()

    def find(self, ref: str) -> File | None:
        ref = ref.strip()
        if ref.startswith("@@PLUGINFILE@@/"):
            ref = ref[len("@@PLUGINFILE@@/"):]
        parts = urlsplit(ref)
        if parts.scheme or parts.netloc:
            tail = _pluginfile_tail(ref)
            if not tail:
                return None
            hit = self.by_url.get(tail)
            if hit is None:
                hit = self._by_name(posixpath.basename(tail))
            return hit
        if not parts.path or parts.path.startswith("/"):
            return None
        rel = posixpath.normpath(posixpath.join(self.base, unquote(parts.path)))
        folder, name = posixpath.split(rel)
        return self.by_path.get((_filepath_dir(folder), name)) or self._by_name(name)

    def _by_name(self, name: str) -> File | None:
        hits = self.by_name.get(unquote(name).lower(), [])
        same = [g for g in hits if _filepath_dir(g.filepath) == self.base]
        pick = (same or hits or [None])[0]
        return pick

    def link(self, g: File) -> str | None:
        if g.status != "ok" or not g.local_path:
            return None
        if kind_of(g.mimetype, g.filename) in VIEWABLE:
            return f"#/file/{g.id}?course={self.course_id}"
        return f"/files/{g.id}/{quote(g.filename)}"

    def image(self, g: File) -> str | None:
        if g.status != "ok" or not g.local_path:
            return None
        mime = (g.mimetype or mimetypes.guess_type(g.filename)[0] or "").lower()
        return f"/files/{g.id}/{quote(g.filename)}" if mime in IMAGE_TYPES else None

    def module_link(self, url: str) -> str | None:
        """A Moodle link to another activity of the course, if the app has its page/file."""
        m = re.search(r"/mod/[a-z0-9_]+/view\.php\?(?:[^#]*&)?id=(\d+)", url)
        if not m:
            return None
        with session(self.engine) as s:
            files = s.exec(
                select(File).where(File.module_id == int(m.group(1)), File.status == "ok")
                .order_by(File.id)
            ).all()
        viewable = [g for g in files if kind_of(g.mimetype, g.filename) in VIEWABLE]
        return self.link(viewable[0]) if viewable else None


def _pluginfile_tail(url: str) -> str:
    """The path after ``pluginfile.php/`` without the context id and query, unquoted."""
    m = re.search(r"pluginfile\.php/\d+/([^?#]+)", url or "")
    return unquote(m.group(1)).strip("/") if m else ""


def _safe_external(url: str) -> str | None:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() in {"http", "https"} and parts.netloc:
        return url.strip()
    if parts.scheme.lower() == "mailto":
        return url.strip()
    return None


def sanitise(html: str, resolver: _Resolver, lang: str = "") -> tuple[str, str, set[int]]:
    """(clean HTML, first heading text, ids of sibling files the page uses)."""
    from bs4 import BeautifulSoup, Comment

    html = resolve_multilang(html, lang)
    soup = BeautifulSoup(html, "html.parser")
    root = soup.body or soup
    for c in root.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    for tag in root.find_all(DROP):
        tag.decompose()

    for tag in root.find_all(EMBEDS):
        if tag.parent is None:
            continue
        src = tag.get("src") or ""
        if not src:
            inner = tag.find("source")
            src = inner.get("src", "") if inner else ""
        target = None
        if src:
            g = resolver.find(src)
            if g is not None:
                resolver.used.add(g.id)
                target = resolver.link(g)
            elif not _pluginfile_tail(src):
                target = _safe_external(src)
        if target:
            a = soup.new_tag("a", href=target)
            label = "video" if tag.name == "video" else "audio" if tag.name == "audio" else "content"
            host = urlsplit(target).netloc
            a.string = f"Open embedded {label}" + (f" ({host})" if host else "")
            p = soup.new_tag("p")
            p.append(a)
            tag.replace_with(p)
        else:
            tag.decompose()

    for tag in list(root.find_all(True)):
        if tag.parent is None:
            continue
        name = tag.name.lower()
        if name not in ALLOWED:
            tag.unwrap()
            continue
        allowed = ATTRS.get(name, set())
        tag.attrs = {k: v for k, v in tag.attrs.items() if k.lower() in allowed}
        if name == "a":
            href = tag.get("href", "")
            if isinstance(href, list):
                href = " ".join(href)
            target = None
            if href.startswith("#") and re.fullmatch(r"#[\w.:-]{1,100}", href):
                target = None  # in-page anchors can't work inside the app's hash router
            elif href:
                g = resolver.find(href)
                if g is not None:
                    resolver.used.add(g.id)
                    target = resolver.link(g)
                else:
                    target = resolver.module_link(href) if "/mod/" in href else None
                    target = target or _safe_external(href)
            if target:
                tag["href"] = target
            else:
                tag.attrs.pop("href", None)
        elif name == "img":
            src = tag.get("src", "")
            g = resolver.find(src) if src else None
            url = None
            if g is not None:
                resolver.used.add(g.id)
                url = resolver.image(g)
            elif src and not _pluginfile_tail(src) and urlsplit(src).scheme.lower() == "https":
                url = src.strip()
            if url:
                tag["src"] = url
            else:
                alt = (tag.get("alt") or "").strip()
                if alt:
                    tag.replace_with(soup.new_string(f"[{alt}]"))
                else:
                    tag.decompose()
        elif name in {"td", "th"}:
            for k in ("colspan", "rowspan"):
                if k in tag.attrs and not str(tag[k]).isdigit():
                    del tag[k]

    heading = ""
    first = root.find(["h1", "h2", "h3", "h4"])
    if first is not None:
        heading = " ".join(first.get_text(" ").split())[:MAX_TITLE]
    body = root.decode_contents() if root is not soup else str(soup)
    return body.strip(), heading, set(resolver.used)
