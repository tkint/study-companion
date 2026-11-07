"""A tiny PDF writer (no dependency): pages with rectangles, lines and text in the standard
PDF fonts (Helvetica, Helvetica-Bold, Helvetica-Oblique, Times-Roman), WinAnsi encoded.

Enough for the printed study weeks (``app.planner.print_week``). Coordinates are PDF points
from the bottom left; ``Page`` flips them so callers think top-down like a screen.
"""

from __future__ import annotations

import zlib

FONTS = {"F1": "Helvetica", "F2": "Helvetica-Bold", "F3": "Helvetica-Oblique", "F4": "Times-Roman"}
REGULAR, BOLD, ITALIC, SERIF = "F1", "F2", "F3", "F4"

# Helvetica advance widths (1/1000 em) for ASCII 32..126, from the standard AFM metrics.
_HELV = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]


def text_width(text: str, size: float, font: str = REGULAR) -> float:
    """Approximate width in points (bold about 7% wider; other characters as a digit)."""
    w = sum(_HELV[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in text)
    if font == BOLD:
        w *= 1.07
    elif font == SERIF:
        w *= 0.9
    return w * size / 1000


def fit(text: str, width: float, size: float, font: str = REGULAR) -> str:
    """``text`` cut with "..." so it fits in ``width`` points."""
    if text_width(text, size, font) <= width:
        return text
    while text and text_width(text + "...", size, font) > width:
        text = text[:-1]
    return (text.rstrip() + "...") if text else ""


def wrap(text: str, width: float, size: float, font: str = REGULAR) -> list[str]:
    """``text`` broken into lines that fit in ``width`` points (words kept whole when they
    fit on a line, else split). Nothing is cut."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        cand = f"{cur} {word}" if cur else word
        if text_width(cand, size, font) <= width:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        while text_width(word, size, font) > width and len(word) > 1:
            n = len(word)
            while n > 1 and text_width(word[:n], size, font) > width:
                n -= 1
            lines.append(word[:n])
            word = word[n:]
        cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def _pdf_text(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _rgb(color: tuple[float, float, float]) -> str:
    return " ".join(f"{c:.3f}" for c in color)


class Page:
    def __init__(self, width: float, height: float) -> None:
        self.width, self.height = width, height
        self.ops: list[bytes] = []

    def _y(self, top: float) -> float:
        return self.height - top

    def rect(self, x: float, top: float, w: float, h: float, fill=None, stroke=None,
             line: float = 0.6, dash: bool = False) -> None:
        if fill is None and stroke is None:
            return
        op = [f"{line:.2f} w", "[2 2] 0 d" if dash else "[] 0 d"]
        if fill is not None:
            op.append(f"{_rgb(fill)} rg")
        if stroke is not None:
            op.append(f"{_rgb(stroke)} RG")
        op.append(f"{x:.2f} {self._y(top + h):.2f} {w:.2f} {h:.2f} re")
        op.append("B" if fill is not None and stroke is not None else "f" if fill is not None else "S")
        self.ops.append((" ".join(op)).encode())

    def line(self, x1: float, top1: float, x2: float, top2: float, color=(0, 0, 0),
             width: float = 0.6) -> None:
        self.ops.append(f"[] 0 d {width:.2f} w {_rgb(color)} RG {x1:.2f} {self._y(top1):.2f} m "
                        f"{x2:.2f} {self._y(top2):.2f} l S".encode())

    def text(self, x: float, baseline: float, text: str, size: float = 9, font: str = REGULAR,
             color=(0, 0, 0)) -> float:
        """Draws ``text`` with its baseline at ``baseline`` (from the top); returns its width."""
        self.ops.append(f"BT /{font} {size:.2f} Tf {_rgb(color)} rg {x:.2f} {self._y(baseline):.2f} Td (".encode()
                        + _pdf_text(text) + b") Tj ET")
        return text_width(text, size, font)

    def centered(self, cx: float, baseline: float, text: str, size: float = 9, font: str = REGULAR) -> None:
        self.text(cx - text_width(text, size, font) / 2, baseline, text, size, font)


class Document:
    def __init__(self, width: float = 842, height: float = 595, title: str = "") -> None:
        self.width, self.height, self.title = width, height, title
        self.pages: list[Page] = []

    def page(self) -> Page:
        p = Page(self.width, self.height)
        self.pages.append(p)
        return p

    def render(self) -> bytes:
        objs: list[bytes] = []

        def add(body: bytes) -> int:
            objs.append(body)
            return len(objs)

        catalog = add(b"")  # filled in below
        pages_id = add(b"")
        fonts = {name: add(f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} "
                           f"/Encoding /WinAnsiEncoding >>".encode())
                 for name, base in FONTS.items()}
        font_res = " ".join(f"/{n} {i} 0 R" for n, i in fonts.items())
        kids = []
        for p in self.pages or [self.page()]:
            data = zlib.compress(b"\n".join(p.ops))
            content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data
                          + b"\nendstream")
            kids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {p.width:g} "
                            f"{p.height:g}] /Resources << /Font << {font_res} >> >> "
                            f"/Contents {content} 0 R >>".encode()))
        objs[pages_id - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                              f"/Count {len(kids)} >>").encode()
        objs[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
        info = add(b"<< /Title (" + _pdf_text(self.title) + b") /Producer (Study Companion) >>")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objs, start=1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode()
        return bytes(out)
