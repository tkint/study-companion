"""Text helpers for multilingual courses (English, French, Spanish and others).

* ``clean_text`` turns Moodle HTML/format strings into plain Unicode text (NFC), resolving
  Moodle's multilang markup (``<span lang="fr" class="multilang">`` and ``{mlang fr}``) to
  the course's language when the filter was not applied server-side.
* ``normalise_lang`` maps Moodle language codes (``fr_ch``, ``es_mx``, ``en_us``) to their
  base ISO 639-1 code.
* ``detect_lang`` is a small stop-word heuristic for courses whose language Moodle does not
  record (the course ``lang`` field is empty unless a teacher forced it). No external service.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter

_MULTILANG_SPAN = re.compile(
    r'<(span|div)\b[^>]*\blang="([A-Za-z_-]+)"[^>]*\bclass="multilang"[^>]*>(.*?)</\1>'
    r'|<(span|div)\b[^>]*\bclass="multilang"[^>]*\blang="([A-Za-z_-]+)"[^>]*>(.*?)</\4>',
    re.IGNORECASE | re.DOTALL,
)
_MLANG = re.compile(r"\{mlang\s+([A-Za-z_-]+)\}(.*?)\{mlang\}", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|table)\b[^>]*>", re.IGNORECASE)
_SPACES = re.compile(r"[ \t ]+")
_NEWLINES = re.compile(r"\n\s*\n+")


def normalise_lang(code: str | None) -> str:
    code = (code or "").strip().lower().replace("-", "_")
    base = code.split("_", 1)[0]
    return base if re.fullmatch(r"[a-z]{2,3}", base) else ""


def _match_parts(pattern: re.Pattern[str], m: re.Match[str]) -> tuple[str, str]:
    if pattern is _MLANG:
        return m.group(1), m.group(2)
    return (m.group(2), m.group(3)) if m.group(2) else (m.group(5), m.group(6))


def _resolve_multilang(text: str, lang: str) -> str:
    """Replace each run of adjacent multilang variants with the best one for ``lang``."""

    def pick(variants: list[tuple[str, str]]) -> str:
        for want in (lang, "en"):
            for code, body in variants:
                if want and normalise_lang(code) == want:
                    return body
        return variants[0][1]

    for pattern in (_MULTILANG_SPAN, _MLANG):
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        out: list[str] = []
        run: list[tuple[str, str]] = []
        pos = 0
        for m in matches:
            gap = text[pos:m.start()]
            if run and gap.strip():
                out.append(pick(run))
                run = []
            if not run:
                out.append(gap)
            run.append(_match_parts(pattern, m))
            pos = m.end()
        out.append(pick(run))
        out.append(text[pos:])
        text = "".join(out)
    return text


def resolve_multilang(html: str, lang: str = "") -> str:
    """Moodle HTML with each multilang run reduced to the variant for ``lang``."""
    return _resolve_multilang(html or "", normalise_lang(lang))


def clean_text(value: str | None, lang: str = "", *, keep_lines: bool = True) -> str:
    """Plain text from a Moodle string (HTML allowed). Never returns None."""
    if not value:
        return ""
    text = _resolve_multilang(str(value), normalise_lang(lang))
    text = _BLOCK.sub("\n", text) if keep_lines else text
    text = _TAG.sub(" " if not keep_lines else "", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFC", text)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    text = _SPACES.sub(" ", text)
    if keep_lines:
        lines = [line.strip() for line in text.split("\n")]
        text = _NEWLINES.sub("\n\n", "\n".join(lines))
    else:
        text = " ".join(text.split())
    return text.strip()


_STOPWORDS = {
    "en": set(
        "the and of to in is for with on this that are be by an you your will week course "
        "introduction chapter lecture assignment exercises from as at or it"
        .split()
    ),
    "fr": set(
        "le la les et des du de un une est pour dans sur avec ce cette sont par vous votre au "
        "aux semaine cours chapitre exercices devoir travail ou en qui"
        .split()
    ),
    "es": set(
        "el la los las y del de un una es para en con por este esta son su sus semana curso "
        "capítulo ejercicios tarea trabajo o que al"
        .split()
    ),
}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def detect_lang(text: str, min_hits: int = 5) -> str:
    """Return ``en``, ``fr`` or ``es`` when the text clearly matches one, else ``""``."""
    words = [w.lower() for w in _WORD.findall(text or "")]
    if not words:
        return ""
    scores: Counter[str] = Counter()
    for word in words:
        for lang, stop in _STOPWORDS.items():
            if word in stop:
                scores[lang] += 1
    # Accented letters are strong hints between French and Spanish.
    joined = " ".join(words)
    scores["es"] += 2 * sum(joined.count(c) for c in "ñ¿¡") + sum(joined.count(c) for c in "áíóú")
    scores["fr"] += sum(joined.count(c) for c in "èêàçùœâîôû")
    if not scores:
        return ""
    (best, top), *rest = scores.most_common()
    second = rest[0][1] if rest else 0
    if top >= min_hits and top >= 1.5 * max(second, 1):
        return best
    return ""
