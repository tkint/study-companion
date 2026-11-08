"""A tiny .xlsx writer (no dependency): sheets of text cells with fonts, fills, borders,
wrapping, merged cells, column widths, row heights, frozen panes and a landscape print
setup. Cells can hold rich text (runs, some bold).

Enough for the study weeks as a spreadsheet (``app.planner.sheet_week``). An .xlsx file is a
zip of XML parts (Office Open XML, ECMA-376); this writes the smallest set Excel, LibreOffice
and Google Sheets open without complaint. Strings are inline (no shared string table).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from xml.sax.saxutils import escape

MAX_NAME = 31  # Excel's limit on sheet names
_BAD_NAME = re.compile(r"[\[\]:*?/\\]")
# Characters XML 1.0 can't carry (control characters other than tab, newline, return).
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
MAX_TEXT = 32767  # Excel's limit on a cell's text


@dataclass(frozen=True)
class Style:
    bold: bool = False
    italic: bool = False
    size: float = 10
    color: str = ""  # text colour, "#rrggbb"
    fill: str = ""  # background, "#rrggbb"
    border: bool = False  # thin grey border on all sides
    wrap: bool = False
    valign: str = "top"  # top, center, bottom
    halign: str = ""  # left, center, right ("" = general)


Rich = list[tuple[str, bool]]  # (text, bold) runs


def _clean(text: str) -> str:
    return _BAD_XML.sub("", text)[:MAX_TEXT]


def _argb(hex_color: str) -> str:
    return "FF" + hex_color.lstrip("#").upper()


def col_name(col: int) -> str:
    """1 -> A, 27 -> AA."""
    out = ""
    while col:
        col, rem = divmod(col - 1, 26)
        out = chr(65 + rem) + out
    return out


def ref(row: int, col: int) -> str:
    return f"{col_name(col)}{row}"


def sheet_name(name: str, taken: set[str] = frozenset()) -> str:  # type: ignore[assignment]
    """A name Excel accepts: no ``[]:*?/\\``, not empty, at most 31 characters, unique
    (case-insensitive) among ``taken``."""
    base = _BAD_NAME.sub("-", _clean(name)).strip("'").strip() or "Sheet"
    base = base[:MAX_NAME]
    out, n = base, 2
    lower = {t.lower() for t in taken}
    while out.lower() in lower:
        suffix = f" ({n})"
        out, n = base[:MAX_NAME - len(suffix)] + suffix, n + 1
    return out


class Sheet:
    def __init__(self, name: str) -> None:
        self.name = name
        self.cells: dict[tuple[int, int], tuple[str | Rich, Style | None]] = {}
        self.merges: list[tuple[int, int, int, int]] = []
        self.widths: dict[int, float] = {}
        self.heights: dict[int, float] = {}
        self.frozen: tuple[int, int] | None = None  # first scrolling row and column
        self.landscape = False

    def set(self, row: int, col: int, value: str | Rich = "", style: Style | None = None) -> None:
        """Put text (or rich text runs) in a cell, 1-based ``row`` and ``col``."""
        self.cells[(row, col)] = (value, style)

    def style(self, row: int, col: int, style: Style) -> None:
        """Style a cell, keeping its value."""
        value = self.cells.get((row, col), ("", None))[0]
        self.cells[(row, col)] = (value, style)

    def get(self, row: int, col: int) -> str | Rich:
        return self.cells.get((row, col), ("", None))[0]

    def merge(self, row1: int, col1: int, row2: int, col2: int) -> None:
        if (row1, col1) != (row2, col2):
            self.merges.append((row1, col1, row2, col2))

    def width(self, col: int, chars: float) -> None:
        self.widths[col] = chars

    def height(self, row: int, points: float) -> None:
        self.heights[row] = points

    def freeze(self, row: int, col: int) -> None:
        """Rows above ``row`` and columns left of ``col`` stay put when scrolling."""
        self.frozen = (row, col)

    def _xml(self, styles: "_Styles") -> str:
        rows: dict[int, list[int]] = {}
        for r, c in self.cells:
            rows.setdefault(r, []).append(c)
        for r in self.heights:
            rows.setdefault(r, [])
        max_r = max(rows, default=1)
        max_c = max((c for r, c in self.cells), default=1)
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
        if self.landscape:
            out.append('<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>')
        out.append(f'<dimension ref="A1:{ref(max_r, max_c)}"/>')
        if self.frozen and self.frozen != (1, 1):
            r, c = self.frozen
            attrs = (f' xSplit="{c - 1}"' if c > 1 else "") + (f' ySplit="{r - 1}"' if r > 1 else "")
            pane = "bottomRight" if r > 1 and c > 1 else ("bottomLeft" if r > 1 else "topRight")
            out.append(f'<sheetViews><sheetView workbookViewId="0"><pane{attrs} '
                       f'topLeftCell="{ref(r, c)}" activePane="{pane}" state="frozen"/>'
                       f'<selection pane="{pane}" activeCell="{ref(r, c)}" sqref="{ref(r, c)}"/>'
                       '</sheetView></sheetViews>')
        else:
            out.append('<sheetViews><sheetView workbookViewId="0"/></sheetViews>')
        out.append('<sheetFormatPr defaultRowHeight="15"/>')
        if self.widths:
            out.append("<cols>" + "".join(
                f'<col min="{c}" max="{c}" width="{w:g}" customWidth="1"/>'
                for c, w in sorted(self.widths.items())) + "</cols>")
        out.append("<sheetData>")
        for r in sorted(rows):
            ht = (f' ht="{self.heights[r]:g}" customHeight="1"' if r in self.heights else "")
            out.append(f'<row r="{r}"{ht}>')
            for c in sorted(rows[r]):
                value, style = self.cells[(r, c)]
                s = f' s="{styles.index(style)}"' if style else ""
                if isinstance(value, list):
                    runs = "".join(
                        "<r>" + ('<rPr><b/>' if bold else "<rPr>") + styles.run_font(style)
                        + f'</rPr><t xml:space="preserve">{escape(_clean(text))}</t></r>'
                        for text, bold in value if text)
                    out.append(f'<c r="{ref(r, c)}"{s} t="inlineStr"><is>{runs}</is></c>')
                elif value:
                    out.append(f'<c r="{ref(r, c)}"{s} t="inlineStr"><is>'
                               f'<t xml:space="preserve">{escape(_clean(value))}</t></is></c>')
                else:
                    out.append(f'<c r="{ref(r, c)}"{s}/>')
            out.append("</row>")
        out.append("</sheetData>")
        if self.merges:
            out.append(f'<mergeCells count="{len(self.merges)}">' + "".join(
                f'<mergeCell ref="{ref(a, b)}:{ref(c, d)}"/>' for a, b, c, d in self.merges)
                + "</mergeCells>")
        out.append('<pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>')
        if self.landscape:
            out.append('<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>')
        out.append("</worksheet>")
        return "".join(out)


class _Styles:
    def __init__(self) -> None:
        self.fonts: list[str] = ['<font><sz val="10"/><name val="Calibri"/></font>']
        self.fills: list[str] = ['<fill><patternFill patternType="none"/></fill>',
                                 '<fill><patternFill patternType="gray125"/></fill>']
        self.borders: list[str] = ["<border><left/><right/><top/><bottom/><diagonal/></border>"]
        self.xfs: list[str] = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>']
        self._xf_index: dict[Style, int] = {}

    @staticmethod
    def _add(table: list[str], xml: str) -> int:
        if xml not in table:
            table.append(xml)
        return table.index(xml)

    @staticmethod
    def _font_props(style: Style) -> str:
        color = f'<color rgb="{_argb(style.color)}"/>' if style.color else ""
        return ("<i/>" if style.italic else "") + f'<sz val="{style.size:g}"/>{color}'

    def run_font(self, style: Style | None) -> str:
        """The font of a rich text run (bold is set per run)."""
        return self._font_props(style or Style()) + '<rFont val="Calibri"/>'

    def index(self, style: Style) -> int:
        if style in self._xf_index:
            return self._xf_index[style]
        font = self._add(self.fonts, "<font>" + ("<b/>" if style.bold else "")
                         + self._font_props(style) + '<name val="Calibri"/></font>')
        fill = 0
        if style.fill:
            fill = self._add(self.fills, f'<fill><patternFill patternType="solid"><fgColor '
                             f'rgb="{_argb(style.fill)}"/><bgColor indexed="64"/></patternFill></fill>')
        border = 0
        if style.border:
            side = '<{0} style="thin"><color rgb="FFB0B0B0"/></{0}>'
            border = self._add(self.borders, "<border>" + "".join(
                side.format(s) for s in ("left", "right", "top", "bottom")) + "<diagonal/></border>")
        align = f' vertical="{style.valign}"' + (f' horizontal="{style.halign}"' if style.halign else "")
        align += ' wrapText="1"' if style.wrap else ""
        xf = (f'<xf numFmtId="0" fontId="{font}" fillId="{fill}" borderId="{border}" xfId="0" '
              f'applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
              f'<alignment{align}/></xf>')
        self._xf_index[style] = self._add(self.xfs, xf)
        return self._xf_index[style]

    def xml(self) -> str:
        def table(tag: str, items: list[str]) -> str:
            return f'<{tag} count="{len(items)}">' + "".join(items) + f"</{tag}>"

        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                + table("fonts", self.fonts) + table("fills", self.fills)
                + table("borders", self.borders)
                + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                + table("cellXfs", self.xfs)
                + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                + "</styleSheet>")


class Workbook:
    def __init__(self, title: str = "") -> None:
        self.title = title
        self.sheets: list[Sheet] = []

    def sheet(self, name: str) -> Sheet:
        """A new sheet; the name is made valid and unique (``sheet_name``)."""
        ws = Sheet(sheet_name(name, {s.name for s in self.sheets}))
        self.sheets.append(ws)
        return ws

    def render(self) -> bytes:
        if not self.sheets:
            self.sheet("Sheet1")
        styles = _Styles()
        parts = {f"xl/worksheets/sheet{i}.xml": ws._xml(styles)
                 for i, ws in enumerate(self.sheets, 1)}
        n = range(1, len(self.sheets) + 1)
        main = "application/vnd.openxmlformats-officedocument.spreadsheetml"
        rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        parts["[Content_Types].xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{main}.sheet.main+xml"/>'
            f'<Override PartName="/xl/styles.xml" ContentType="{main}.styles+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                      f'ContentType="{main}.worksheet+xml"/>' for i in n)
            + '<Override PartName="/docProps/core.xml" '
              'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            "</Types>")
        parts["_rels/.rels"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/'
            'relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            "</Relationships>")
        parts["docProps/core.xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
            'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>{escape(_clean(self.title))}</dc:title></cp:coreProperties>")
        parts["xl/workbook.xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'xmlns:r="{rel}"><bookViews><workbookView/></bookViews><sheets>'
            + "".join(f'<sheet name="{escape(ws.name, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
                      for i, ws in zip(n, self.sheets))
            + "</sheets></workbook>")
        parts["xl/_rels/workbook.xml.rels"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" '
                      f'Target="worksheets/sheet{i}.xml"/>' for i in n)
            + f'<Relationship Id="rId{len(self.sheets) + 1}" Type="{rel}/styles" Target="styles.xml"/>'
            "</Relationships>")
        parts["xl/styles.xml"] = styles.xml()

        buf = BytesIO()
        order = ["[Content_Types].xml", "_rels/.rels", "docProps/core.xml", "xl/workbook.xml",
                 "xl/_rels/workbook.xml.rels", "xl/styles.xml"]
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name in order + [p for p in parts if p not in order]:
                z.writestr(name, parts[name])
        return buf.getvalue()
