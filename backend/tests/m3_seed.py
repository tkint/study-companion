"""Test data for M3: a small course with real PDF/DOCX/PPTX/HTML files on disk."""

from __future__ import annotations

import time
from pathlib import Path

from app.db import session
from app.models import Course, Deadline, File, Module, Section

NOW = int(time.time())
DAY = 86400


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of Helvetica text per page."""
    n = len(pages)
    objects: list[bytes] = []
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(pages):
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_docx(path: Path, paragraphs: list[str]) -> None:
    import docx

    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    table = d.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Term"
    table.rows[0].cells[1].text = "Matrice"
    d.save(str(path))


def make_pptx(path: Path, slides: list[tuple[str, str]]) -> None:
    from pptx import Presentation

    deck = Presentation()
    for title, note in slides:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
        slide.notes_slide.notes_text_frame.text = note
    deck.save(str(path))


def write(data_dir: Path, rel: str, content: bytes | None = None) -> str:
    path = data_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if content is not None:
        path.write_bytes(content)
    return rel


def seed(engine, data_dir: Path) -> None:
    """Course 10 "Linear Algebra" (French) with 3 sections, course 11 "Statistics"."""
    base = "courses/LA"
    pdf = write(data_dir, f"{base}/01 Vecteurs/cours.pdf",
                make_pdf(["Les vecteurs et les matrices", "Le produit scalaire",
                          "Valeurs propres et vecteurs propres"]))
    docx_rel = write(data_dir, f"{base}/02 Matrices/td.docx")
    make_docx(data_dir / docx_rel, ["Exercice 1: inverser une matrice", "Exercice 2: determinant"])
    pptx_rel = write(data_dir, f"{base}/03 Eigen/slides.pptx")
    make_pptx(data_dir / pptx_rel, [("Eigenvalues", "Speaker note about diagonalisation"),
                                    ("Spectral theorem", "")])
    html = write(data_dir, f"{base}/03 Eigen/page/index.html",
                 b"<html><body><h1>Lecture page</h1><p>Read chapter 5 before Monday.</p>"
                 b"<script>alert(1)</script></body></html>")
    with session(engine) as s:
        s.add(Course(id=10, shortname="LA", fullname="Linear Algebra", lang="fr",
                     enrolled=True, folder="LA"))
        s.add(Course(id=11, shortname="STAT", fullname="Statistics", lang="en",
                     enrolled=True, folder="STAT"))
        s.add(Course(id=12, shortname="OLD", fullname="Old course", enrolled=False))
        s.add(Section(id=100, course_id=10, number=0, name="General"))
        s.add(Section(id=101, course_id=10, number=1, name="Vecteurs", summary="Bases des vecteurs"))
        s.add(Section(id=102, course_id=10, number=2, name="Matrices"))
        s.add(Section(id=103, course_id=10, number=3, name="Eigen"))
        s.add(Section(id=110, course_id=11, number=1, name="Descriptive statistics",
                      summary="Mean, median and variance"))
        s.flush()
        s.add(Module(id=1000, course_id=10, section_id=101, modname="resource", name="Cours",
                     completion_state=1, position=0))
        s.add(Module(id=1001, course_id=10, section_id=102, modname="resource", name="TD",
                     position=0))
        s.add(Module(id=1002, course_id=10, section_id=102, modname="assign", name="Devoir 1",
                     description="Inverser trois matrices et rendre un PDF.", completion_state=0,
                     position=1))
        s.add(Module(id=1003, course_id=10, section_id=103, modname="resource", name="Slides",
                     position=0))
        s.add(Module(id=1004, course_id=10, section_id=103, modname="page", name="Lecture page",
                     position=1))
        s.add(Module(id=1005, course_id=10, section_id=103, modname="label", name="Note",
                     description="Exam on chapter 5", position=2))
        s.add(Module(id=1100, course_id=11, section_id=110, modname="label", name="Intro",
                     description="Welcome to statistics", position=0))
        s.flush()
        s.add(File(id=1, module_id=1000, course_id=10, section_id=101, filename="cours.pdf",
                   mimetype="application/pdf", filesize=900, timemodified=NOW - 60 * DAY,
                   status="ok", local_path=pdf, downloaded_timemodified=NOW - 60 * DAY,
                   downloaded_size=900))
        s.add(File(id=2, module_id=1001, course_id=10, section_id=102, filename="td.docx",
                   mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                   filesize=5000, timemodified=NOW - 30 * DAY, status="ok", local_path=docx_rel,
                   downloaded_timemodified=NOW - 30 * DAY, downloaded_size=5000))
        s.add(File(id=3, module_id=1003, course_id=10, section_id=103, filename="slides.pptx",
                   mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                   filesize=30000, timemodified=NOW - 5 * DAY, status="ok", local_path=pptx_rel,
                   downloaded_timemodified=NOW - 5 * DAY, downloaded_size=30000))
        s.add(File(id=4, module_id=1004, course_id=10, section_id=103, filename="index.html",
                   mimetype="text/html", filesize=120, timemodified=NOW - 5 * DAY, status="ok",
                   local_path=html, downloaded_timemodified=NOW - 5 * DAY, downloaded_size=120))
        s.add(File(id=5, module_id=1003, course_id=10, section_id=103, filename="lecture.mp4",
                   mimetype="video/mp4", filesize=10**9, status="skipped_size"))
        s.add(Deadline(id=1, source="assign", source_id=1, course_id=10, module_id=1002,
                       name="Devoir 1", kind="due", due_at=NOW + 3 * DAY, grade=20,
                       description="Inverser trois matrices."))
        s.add(Deadline(id=2, source="quiz", source_id=2, course_id=11, name="Quiz 1",
                       kind="close", due_at=NOW - 2 * DAY))
        s.commit()
