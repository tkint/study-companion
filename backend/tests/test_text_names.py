from pathlib import Path

import pytest

from app.moodle.names import MAX_NAME_CHARS, UnsafePathError, safe_join, safe_name, safe_relpath
from app.moodle.text import clean_text, detect_lang, normalise_lang


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Cours 1.pdf", "Cours 1.pdf"),
        ("../../etc/passwd", "_.._etc_passwd"),
        ("..", "untitled"),
        ("a/b\\c:d*e?.txt", "a_b_c_d_e_.txt"),
        ("  .hidden  ", "hidden"),
        ("CON.txt", "_CON.txt"),
        ("Résumé – leçoń.pdf", "Résumé – leçoń.pdf".replace("ń", "ń")),
        ("tab\tand\nnewline", "tabandnewline"),
        ("", "untitled"),
    ],
)
def test_safe_name(raw, expected):
    assert safe_name(raw) == expected


def test_safe_name_truncates_but_keeps_extension():
    name = safe_name("é" * 500 + ".pdf")
    assert name.endswith(".pdf")
    assert len(name) <= MAX_NAME_CHARS
    assert len(name.encode()) <= 240


def test_safe_relpath_drops_traversal():
    assert safe_relpath("/../../sub/./dir/") == ["sub", "dir"]
    assert safe_relpath(None) == []


def test_safe_join_blocks_escape(tmp_path: Path):
    assert safe_join(tmp_path, "a", "b.txt") == tmp_path.resolve() / "a" / "b.txt"
    with pytest.raises(UnsafePathError):
        safe_join(tmp_path, "..", "x")


def test_normalise_lang():
    assert normalise_lang("fr_ch") == "fr"
    assert normalise_lang("es-MX") == "es"
    assert normalise_lang("EN") == "en"
    assert normalise_lang("") == ""
    assert normalise_lang("not a lang") == ""


def test_clean_text_html_entities_and_accents():
    assert clean_text("<p>L&#39;alg&egrave;bre&nbsp;lin&eacute;aire</p><p>Año</p>") == (
        "L'algèbre linéaire\n\nAño"
    )
    assert clean_text(None) == ""


def test_clean_text_resolves_multilang_spans():
    raw = ('<span lang="es" class="multilang">Historia</span>'
           '<span lang="en" class="multilang">History</span> 101')
    assert clean_text(raw, "es") == "Historia 101"
    assert clean_text(raw, "en") == "History 101"
    assert clean_text(raw, "de") == "History 101"  # falls back to English
    assert clean_text(raw, "") == "History 101"


def test_clean_text_resolves_mlang_tags():
    raw = "{mlang fr}Devoir{mlang}{mlang es}Tarea{mlang}{mlang other}Homework{mlang}"
    assert clean_text(raw, "fr_ch") == "Devoir"
    assert clean_text(raw, "es") == "Tarea"


@pytest.mark.parametrize(
    "text,lang",
    [
        ("This week we cover the basics of sorting and the analysis of algorithms.", "en"),
        ("Cette semaine nous verrons les vecteurs et les matrices dans le cours.", "fr"),
        ("Este curso es una introducción a la historia de la región, con lecturas.", "es"),
        ("Ok", ""),
    ],
)
def test_detect_lang(text, lang):
    assert detect_lang(text) == lang
