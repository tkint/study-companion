"""MCP read tools (text output, paging, errors)."""

from datetime import datetime, timedelta

import pytest

from app.db import make_engine
from app.extract.index import extract_files, index_structure
from app.mcp_tools import StudyTools, ToolInputError, parse_pages
from app import mcp_tools

from .m3_seed import seed


@pytest.fixture
def tools(settings):
    engine = make_engine(settings.data_dir)
    seed(engine, settings.data_dir)
    extract_files(engine, settings.data_dir)
    index_structure(engine)
    return StudyTools(settings, engine, "https://study.example.ch")


def day(offset: int) -> str:
    return (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")


def test_parse_pages():
    assert parse_pages(None, 30) == list(range(1, 11))
    assert parse_pages("3", 30) == [3]
    assert parse_pages("2,4,7-9", 30) == [2, 4, 7, 8, 9]
    assert parse_pages("28-", 30) == [28, 29, 30]
    assert parse_pages("5-100", 6) == [5, 6]
    for bad in ("abc", "5-2", "40"):
        with pytest.raises(ToolInputError):
            parse_pages(bad, 30)


def test_list_courses(tools):
    out = tools.list_courses()
    assert "[10] Linear Algebra (LA)" in out
    assert "7 pages of text" in out
    assert "Old course" not in out
    assert "Old course" in tools.list_courses(include_past=True)


def test_get_deadlines(tools):
    out = tools.get_deadlines()
    assert "Devoir 1" in out and "to do" in out and "max grade 20" in out
    assert "Quiz 1" in out and "OVERDUE" in out
    only = tools.get_deadlines(course_id=11)
    assert "Devoir 1" not in only and "Quiz 1" in only
    assert "0 deadline(s)" in tools.get_deadlines(from_date=day(30), to_date=day(40))
    with pytest.raises(ToolInputError):
        tools.get_deadlines(from_date="yesterday")
    with pytest.raises(ToolInputError):
        tools.get_deadlines(from_date=day(5), to_date=day(1))
    with pytest.raises(ToolInputError):
        tools.get_deadlines(course_id=999)


def test_get_materials_period_and_fallback(tools):
    full = tools.get_materials(10)
    assert "3 section(s)" in full  # the empty "General" section is left out
    assert '"cours.pdf" file_id 1 · 3 pages of text' in full
    assert "too large to download" in full
    assert "✓ done" in full

    recent = tools.get_materials(10, from_date=day(-10))
    assert "Section 1:" not in recent  # PDF uploaded 60 days ago
    assert "Section 3: Eigen" in recent and "Section 2: Matrices" in recent  # deadline in range

    old = tools.get_materials(10, from_date="2001-01-01", to_date="2001-02-01")
    assert "Note: Nothing in this course is dated" in old and "Section 1:" in old

    ranged = tools.get_materials(10, section_from=2, section_to=2)
    assert "Section 2:" in ranged and "Section 3:" not in ranged
    with pytest.raises(ToolInputError):
        tools.get_materials(10, page=5)


def test_get_materials_pages(tools, monkeypatch):
    monkeypatch.setattr(mcp_tools, "SECTIONS_PER_PAGE", 2)
    first = tools.get_materials(10)
    assert "Page 1 of 2. Next: get_materials(course_id=10, page=2)" in first
    assert "Section 3:" in tools.get_materials(10, page=2)


def test_get_section(tools):
    out = tools.get_section(102)
    assert "Assignment: Devoir 1 (not done)" in out
    assert "Inverser trois matrices et rendre un PDF." in out
    with pytest.raises(ToolInputError):
        tools.get_section(9999)


def test_read_file(tools, monkeypatch):
    out = tools.read_file(1, "2-3")
    assert "pages 2-3 of 3" in out and "--- page 2 ---" in out and "--- page 1 ---" not in out
    assert "--- slide 1 ---" in tools.read_file(3)
    assert "Lecture page" in tools.read_file(4) and "alert" not in tools.read_file(4)
    assert "too large to download" in tools.read_file(5)
    with pytest.raises(ToolInputError):
        tools.read_file(1, "9")
    with pytest.raises(ToolInputError):
        tools.read_file(999)

    monkeypatch.setattr(mcp_tools, "MAX_CHARS_PER_READ", 30)
    short = tools.read_file(1, "1-3")
    assert "--- page 1 ---" in short
    assert 'Next: read_file(file_id=1, pages="' in short


def test_read_file_suggests_more_pages(tools, monkeypatch):
    monkeypatch.setattr(mcp_tools, "DEFAULT_READ_PAGES", 1)
    out = tools.read_file(1)
    assert 'More: read_file(file_id=1, pages="2-2")' in out


def test_search_materials(tools):
    out = tools.search_materials("propres")
    assert 'read_file(file_id=1, pages="3")' in out
    assert "No matches" in tools.search_materials("photosynthesis")
    assert "get_section(section_id=102)" in tools.search_materials("devoir")
    with pytest.raises(ToolInputError):
        tools.search_materials("  !! ")


def test_tool_names_match_the_registered_tools(settings):
    from app.mcp_server import build_server
    import asyncio

    server = build_server(StudyTools(settings, make_engine(settings.data_dir)), "test")
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == set(mcp_tools.TOOL_NAMES)
