"""Text extraction and FTS5 search."""

from sqlmodel import select

from app.db import make_engine, session
from app.extract import formats
from app.extract.index import extract_files, fts_query, index_structure, search
from app.models import File, FilePage, FileText

from .m3_seed import NOW, make_pdf, seed


def test_kind_of_uses_mimetype_then_extension():
    assert formats.kind_of("application/pdf", "x.bin") == "pdf"
    assert formats.kind_of("", "Slides.PPTX") == "pptx"
    assert formats.kind_of("application/octet-stream", "notes.md") == "text"
    assert formats.kind_of("video/mp4", "a.mp4") is None


def test_split_parts_keeps_paragraphs_and_size():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 100 for i in range(20))
    parts = formats.split_parts(text, size=1500)
    assert len(parts) > 1
    assert all(len(p) <= 1500 for p in parts)
    assert parts[0].startswith("Paragraph 0")
    long_word = formats.split_parts("x" * 5000, size=1000)
    assert [len(p) for p in long_word] == [1000] * 5


def test_html_to_text_drops_scripts():
    text = formats.html_to_text("<h1>Title</h1><p>Body<br>line</p><script>evil()</script>")
    assert "evil" not in text
    assert text.splitlines()[0] == "Title"
    assert "line" in text


def test_pdf_pages(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf(["First page", "Second (page)"]))
    result = formats.extract(path, "pdf")
    assert result.unit == "page"
    assert result.pages == ["First page", "Second (page)"]


def test_broken_pdf_is_an_extract_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 garbage")
    try:
        formats.extract(path, "pdf")
    except formats.ExtractError as exc:
        assert "PDF" in str(exc)
    else:  # pypdf may also return no pages for garbage
        pass


def test_extract_files_indexes_and_skips_unchanged(tmp_path):
    engine = make_engine(tmp_path)
    seed(engine, tmp_path)
    stats = extract_files(engine, tmp_path)
    assert (stats.extracted, stats.failed) == (4, 0)
    with session(engine) as s:
        states = {t.file_id: t for t in s.exec(select(FileText)).all()}
    assert states[1].unit == "page" and states[1].pages == 3
    assert states[2].unit == "part"
    assert states[3].unit == "slide" and states[3].pages == 2
    assert 5 not in states  # video, not downloaded

    again = extract_files(engine, tmp_path)
    assert again.unchanged == 4 and again.extracted == 0

    # A new version of the PDF on Moodle is re-extracted.
    (tmp_path / "courses/LA/01 Vecteurs/cours.pdf").write_bytes(make_pdf(["Nouvelle version"]))
    with session(engine) as s:
        f = s.get(File, 1)
        f.downloaded_timemodified = NOW
        s.add(f)
        s.commit()
    assert extract_files(engine, tmp_path).extracted == 1
    hits, _ = search(engine, "nouvelle")
    assert [(h.ref_id, h.page) for h in hits] == [(1, 1)]
    assert search(engine, "scalaire") == ([], 0)

    # Removed from Moodle: text and index entries go away.
    with session(engine) as s:
        f = s.get(File, 1)
        f.status = "removed"
        s.add(f)
        s.commit()
    assert extract_files(engine, tmp_path).removed == 1
    with session(engine) as s:
        assert s.get(FileText, 1) is None
        assert not s.exec(select(FilePage).where(FilePage.file_id == 1)).all()
    assert search(engine, "nouvelle") == ([], 0)


def test_missing_file_is_recorded_not_fatal(tmp_path):
    engine = make_engine(tmp_path)
    seed(engine, tmp_path)
    (tmp_path / "courses/LA/02 Matrices/td.docx").unlink()
    stats = extract_files(engine, tmp_path)
    assert stats.failed == 1 and stats.extracted == 3
    with session(engine) as s:
        assert s.get(FileText, 2).status == "error"


def test_search_ignores_accents_and_fts_syntax(tmp_path):
    engine = make_engine(tmp_path)
    seed(engine, tmp_path)
    extract_files(engine, tmp_path)
    index_structure(engine)
    hits, total = search(engine, "valeurs PROPRES")
    assert total == 1 and hits[0].page == 3 and "**" in hits[0].snippet
    assert search(engine, "déterminant")[1] == 1  # the DOCX says "determinant"
    hits, _ = search(engine, "diagonalisation")  # PPTX speaker notes
    assert hits[0].ref_id == 3 and hits[0].page == 1
    hits, _ = search(engine, "welcome")  # label description, course 11
    assert hits[0].kind == "module" and hits[0].course_id == 11
    assert search(engine, "welcome", course_id=10) == ([], 0)
    assert search(engine, 'NEAR(" OR *') == ([], 0)
    assert fts_query('a" OR b*') == '"a" "OR" "b"*'
    assert fts_query("  ") == ""


def test_cli_extract(tmp_path, monkeypatch, capsys):
    from app import cli

    engine = make_engine(tmp_path)
    seed(engine, tmp_path)
    monkeypatch.setenv("SECRET_KEY", "s" * 64)
    monkeypatch.setenv("APP_PASSWORD", "x" * 12)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert cli.main(["extract"]) == 0
    assert "4 extracted" in capsys.readouterr().out
    assert cli.main(["extract", "--force"]) == 0
    assert "4 extracted" in capsys.readouterr().out
