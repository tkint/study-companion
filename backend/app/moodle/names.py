"""Safe file and folder names from Moodle-controlled strings.

Names keep their accents (é, ñ, ç) but lose path separators, control characters, characters
Windows forbids, leading dots and reserved device names. They are truncated to about 200
characters (and 240 UTF-8 bytes, under the 255-byte limit of most filesystems) while keeping
the extension. ``safe_join`` additionally checks the final path stays inside its base.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePosixPath

MAX_NAME_CHARS = 200
MAX_NAME_BYTES = 240

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class UnsafePathError(ValueError):
    pass


def _truncate(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem or len(ext) > 10:
        stem, ext = name, ""
    suffix = f".{ext}" if ext else ""
    max_chars = MAX_NAME_CHARS - len(suffix)
    stem = stem[:max_chars]
    while len((stem + suffix).encode("utf-8")) > MAX_NAME_BYTES:
        stem = stem[:-1]
    return (stem.rstrip(" .") or "_") + suffix


def safe_name(value: str | None, fallback: str = "untitled") -> str:
    name = unicodedata.normalize("NFC", str(value or ""))
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = _FORBIDDEN.sub("_", name)
    name = " ".join(name.split())  # collapse whitespace
    name = name.strip(" .")
    if not name or set(name) <= {"_", "."}:
        name = fallback
    if name.split(".", 1)[0].lower() in _RESERVED:
        name = f"_{name}"
    return _truncate(name)


def safe_relpath(filepath: str | None) -> list[str]:
    """Split a Moodle ``filepath`` (``/sub/dir/``) into safe components, dropping ``..``."""
    parts = []
    for part in PurePosixPath(str(filepath or "/").replace("\\", "/")).parts:
        if part in {"/", ".", ".."} or not part.strip(" ."):
            continue
        parts.append(safe_name(part))
    return parts


def safe_join(base: Path, *parts: str) -> Path:
    base = base.resolve()
    path = base.joinpath(*parts).resolve()
    if path != base and base not in path.parents:
        raise UnsafePathError("path escapes the data directory")
    return path
