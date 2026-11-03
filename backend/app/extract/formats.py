"""Text from course files: PDF (per page), PPTX (per slide, with speaker notes), DOCX,
HTML and plain text (split into parts of about ``PART_CHARS`` characters).

No AI and no OCR: a scanned PDF has no text layer and comes back empty. Every extractor
returns a list of page texts (index 0 is page 1). Limits keep one odd file from using all
of the small server's memory or CPU.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("app.extract")

PART_CHARS = 3000
MAX_PAGES = 3000
MAX_PAGE_CHARS = 20000
MAX_TOTAL_CHARS = 5_000_000

PDF_TYPES = {"application/pdf"}
DOCX_TYPES = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
PPTX_TYPES = {"application/vnd.openxmlformats-officedocument.presentationml.presentation"}
HTML_TYPES = {"text/html", "application/xhtml+xml"}
TEXT_TYPES = {"text/plain", "text/markdown", "text/csv", "text/x-markdown"}
EXTENSIONS = {
    ".pdf": "pdf", ".docx": "docx", ".pptx": "pptx", ".html": "html", ".htm": "html",
    ".xhtml": "html", ".txt": "text", ".md": "text", ".markdown": "text", ".csv": "text",
}


class ExtractError(RuntimeError):
    pass


@dataclass
class Extracted:
    unit: str  # page, slide or part
    pages: list[str] = field(default_factory=list)


def kind_of(mimetype: str, filename: str) -> str | None:
    """The extractor for a file, from its MIME type or else its extension."""
    mimetype = (mimetype or "").split(";")[0].strip().lower()
    if mimetype in PDF_TYPES:
        return "pdf"
    if mimetype in DOCX_TYPES:
        return "docx"
    if mimetype in PPTX_TYPES:
        return "pptx"
    if mimetype in HTML_TYPES:
        return "html"
    if mimetype in TEXT_TYPES:
        return "text"
    return EXTENSIONS.get(Path(filename or "").suffix.lower())


_SPACES = re.compile(r"[ \t\f\v ]+")
_BLANKS = re.compile(r"\n\s*\n\s*\n+")


def tidy(text: str) -> str:
    text = (text or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANKS.sub("\n\n", text).strip()


def split_parts(text: str, size: int = PART_CHARS) -> list[str]:
    """Split text into parts of about ``size`` characters at paragraph (else line, else
    word) boundaries."""
    text = tidy(text)
    if not text:
        return []
    parts: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        while len(para) > size:
            cut = para.rfind("\n", 0, size)
            if cut < size // 2:
                cut = para.rfind(" ", 0, size)
            if cut < size // 2:
                cut = size
            head, para = para[:cut].strip(), para[cut:].strip()
            if current:
                parts.append(current)
                current = ""
            parts.append(head)
        if current and len(current) + len(para) + 2 > size:
            parts.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current:
        parts.append(current)
    return parts


def _limit(pages: list[str]) -> list[str]:
    out, total = [], 0
    for text in pages[:MAX_PAGES]:
        text = text[:MAX_PAGE_CHARS]
        total += len(text)
        if total > MAX_TOTAL_CHARS:
            break
        out.append(text)
    return out


def _pdf(path: Path) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")  # many "protected" course PDFs only restrict editing
            except Exception:
                raise ExtractError("the PDF is password protected") from None
        pages = []
        for i, page in enumerate(reader.pages):
            if i >= MAX_PAGES:
                break
            try:
                pages.append(tidy(page.extract_text() or ""))
            except Exception as exc:  # one broken page shouldn't lose the rest
                logger.info("PDF page %d of %s unreadable: %s", i + 1, path.name, type(exc).__name__)
                pages.append("")
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        raise ExtractError(f"unreadable PDF ({type(exc).__name__})") from None
    return Extracted("page", pages)


def _docx(path: Path) -> Extracted:
    import docx

    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise ExtractError(f"unreadable DOCX ({type(exc).__name__})") from None
    lines: list[str] = []
    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = "".join(t.text or "" for t in child.iter() if t.tag.endswith("}t"))
            lines.append(text)
        elif tag == "tbl":
            for row in child.iter():
                if row.tag.endswith("}tr"):
                    cells = []
                    for cell in row.iterchildren():
                        if cell.tag.endswith("}tc"):
                            cells.append(" ".join(
                                (t.text or "") for t in cell.iter() if t.tag.endswith("}t")
                            ).strip())
                    lines.append(" | ".join(cells))
            lines.append("")
    return Extracted("part", split_parts("\n".join(lines)))


def _pptx(path: Path) -> Extracted:
    from pptx import Presentation

    try:
        deck = Presentation(str(path))
    except Exception as exc:
        raise ExtractError(f"unreadable PPTX ({type(exc).__name__})") from None
    pages = []
    for slide in deck.slides:
        texts = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                texts.append(shape.text_frame.text)
            elif getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    texts.append(" | ".join(cell.text for cell in row.cells))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes is not None and notes.text.strip():
                texts.append("Notes: " + notes.text)
        pages.append(tidy("\n".join(texts)))
    return Extracted("slide", pages)


def html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    block = ["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre"]
    for tag in soup.find_all(block):
        tag.insert_after("\n")
    for cell in soup.find_all(["td", "th"]):
        cell.insert_after(" | ")
    return tidy(soup.get_text())


def _read_text(path: Path) -> str:
    raw = path.read_bytes()[: MAX_TOTAL_CHARS * 2]
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract(path: Path, kind: str) -> Extracted:
    """Extract a file's text. Raises ExtractError for unreadable files."""
    if kind == "pdf":
        result = _pdf(path)
    elif kind == "docx":
        result = _docx(path)
    elif kind == "pptx":
        result = _pptx(path)
    elif kind == "html":
        result = Extracted("part", split_parts(html_to_text(_read_text(path))))
    elif kind == "text":
        result = Extracted("part", split_parts(_read_text(path)))
    else:
        raise ExtractError(f"unsupported file type {kind!r}")
    result.pages = _limit(result.pages)
    return result
