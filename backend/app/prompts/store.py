"""Your edits of the prompt templates, kept in SQLite (the Markdown files stay the defaults).

``validate`` keeps an edited template usable: front matter that parses, a ``{{steps}}``
placeholder, only known placeholders and balanced ``{{#x}}...{{/x}}`` sections, and only
real MCP tool names in anything written like a call (``name(...)``).
"""

from __future__ import annotations

import hashlib
import re
import time

from sqlalchemy.engine import Engine
from sqlmodel import select

from app.db import session
from app.models import PromptTemplateEdit

USER_ID = 1
MAX_CHARS = 20_000
VARIABLES = ("courses", "period", "steps", "language", "depth", "time", "topic", "part", "today")
FLAGS = ("time", "topic", "deadlines", "completion", "save")

_CALL = re.compile(r"\b([a-z]+(?:_[a-z]+)+)\(")
_TAG = re.compile(r"\{\{([#^/]?)([^{}]*)\}\}")


class TemplateError(ValueError):
    pass


def sha(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode()).hexdigest()[:16]


def overrides(engine: Engine, user_id: int = USER_ID) -> dict[str, str]:
    with session(engine) as s:
        rows = s.exec(select(PromptTemplateEdit).where(PromptTemplateEdit.user_id == user_id)).all()
    return {r.template_id: r.text for r in rows}


def validate(template_id: str, text: str) -> list[str]:
    """Problems that would make the template unusable (empty list: fine)."""
    from app import prompts
    from app.mcp_tools import TOOL_NAMES

    if len(text) > MAX_CHARS:
        return [f"The template is too long (over {MAX_CHARS:,} characters)."]
    text = text.replace("\r\n", "\n")
    problems: list[str] = []
    if text.startswith("---") and not prompts._FRONT.match(text):
        problems.append("The front matter (between the two --- lines) is not closed.")
    t = prompts.parse_template(template_id, text)
    if not t.body.strip():
        problems.append("The template has no text.")
    if "{{steps}}" not in t.body:
        problems.append("Keep the {{steps}} placeholder: it lists the Study Companion tool calls.")
    open_sections: list[str] = []
    for kind, name in _TAG.findall(t.body):
        if kind in ("#", "^"):
            if name not in FLAGS:
                problems.append(f"Unknown section {{{{{kind}{name}}}}}; use one of: {', '.join(FLAGS)}.")
            open_sections.append(name)
        elif kind == "/":
            if not open_sections or open_sections[-1] != name:
                problems.append(f"{{{{/{name}}}}} does not close the section opened before it.")
            else:
                open_sections.pop()
        elif name not in VARIABLES:
            problems.append(f"Unknown placeholder {{{{{name}}}}}; use one of: {', '.join(VARIABLES)}.")
    for name in open_sections:
        problems.append(f"The section {{{{#{name}}}}} is never closed with {{{{/{name}}}}}.")
    unknown = sorted({n for n in _CALL.findall(t.body) if n not in TOOL_NAMES})
    if unknown:
        problems.append("Not a Study Companion tool: " + ", ".join(f"{n}()" for n in unknown)
                        + ". Available: " + ", ".join(TOOL_NAMES) + ".")
    return list(dict.fromkeys(problems))


def save(engine: Engine, template_id: str, text: str, user_id: int = USER_ID) -> None:
    from app import prompts

    defaults = prompts.default_sources()
    if template_id not in defaults:
        raise TemplateError("unknown template")
    text = text.replace("\r\n", "\n")
    problems = validate(template_id, text)
    if problems:
        raise TemplateError(" ".join(problems))
    with session(engine) as s:
        row = s.exec(select(PromptTemplateEdit).where(
            PromptTemplateEdit.user_id == user_id, PromptTemplateEdit.template_id == template_id)).first()
        if text.strip() == defaults[template_id].strip():
            if row:  # saved back to the default: nothing to keep
                s.delete(row)
                s.commit()
            return
        row = row or PromptTemplateEdit(user_id=user_id, template_id=template_id)
        row.text = text
        row.base_sha = sha(defaults[template_id])
        row.updated_at = int(time.time())
        s.add(row)
        s.commit()


def reset(engine: Engine, template_id: str, user_id: int = USER_ID) -> bool:
    with session(engine) as s:
        row = s.exec(select(PromptTemplateEdit).where(
            PromptTemplateEdit.user_id == user_id, PromptTemplateEdit.template_id == template_id)).first()
        if not row:
            return False
        s.delete(row)
        s.commit()
        return True


def listing(engine: Engine, user_id: int = USER_ID) -> list[dict]:
    """Every template for the editor: current text, built-in text, whether you edited it."""
    from app import prompts

    defaults = prompts.default_sources()
    with session(engine) as s:
        rows = {r.template_id: r for r in s.exec(
            select(PromptTemplateEdit).where(PromptTemplateEdit.user_id == user_id)).all()}
    current = prompts.load_templates(overrides={k: r.text for k, r in rows.items()})
    out = []
    for tid, t in current.items():
        row = rows.get(tid)
        out.append({
            "id": tid,
            "title": t.title,
            "description": t.description,
            "text": row.text if row else defaults[tid],
            "default_text": defaults[tid],
            "edited": row is not None,
            "updated_at": row.updated_at if row else None,
            # The built-in version changed (app update) since you saved your edit.
            "default_changed": bool(row and row.base_sha != sha(defaults[tid])),
        })
    return out
