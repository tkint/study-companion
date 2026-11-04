"""What counts in a realistic catch-up: mandatory vs optional work, ignored items, the target.

You will not catch up on everything, so the app separates:

- **mandatory** work (the default) from **optional** work. A deadline is optional when its
  name says so (optional, facultatif, bonus, fakultativ, freiwillig, practice,
  entraînement...), when it is an assignment or quiz graded out of 0, or when it is a
  calendar event of a feedback, choice, forum or survey activity. Sections are mandatory.
  You can override either way in the web UI.
- **ignored** items: past work you decided to let go. They leave the plan, the counts and
  the target altogether (you can bring them back).
- the **target**: the share of the mandatory backlog you aim to catch up (60% by default).

Everything is per user (single user id 1 for now).
"""

from __future__ import annotations

import re
import time

from sqlalchemy.engine import Engine
from sqlmodel import select

from app.db import session
from app.models import CatchUpPrefs, Deadline, ItemPref, Section

USER = 1
KINDS = ("deadline", "section")
CRITICALITIES = ("mandatory", "optional")
DEFAULT_TARGET = 60.0
MIN_TARGET, MAX_TARGET = 10.0, 100.0
OPTIONAL_MODULES = {"feedback", "choice", "forum", "survey", "questionnaire", "chat"}
# Words in an activity name that mark it optional (en, fr, de, it), matched as words.
OPTIONAL_WORDS = re.compile(
    r"\b(optional|optionnel(?:le)?s?|facultati(?:f|ve|fs|ves)|bonus|fakultativ\w*|"
    r"freiwillig\w*|practice|practise|entra[iî]nement|[eé]xercices? libres?|"
    r"self[- ]?test|auto[- ]?[eé]valuation|ungraded|non not[eé]e?s?|opzionale)\b",
    re.IGNORECASE,
)
UNSET = object()


class PrefError(ValueError):
    """Bad input: the message is shown in the UI."""


def auto_mandatory(source: str, name: str, grade: float | None, modname: str = "") -> tuple[bool, str]:
    """Whether a deadline is mandatory by default, and why (for the UI and Claude)."""
    if OPTIONAL_WORDS.search(name or ""):
        return False, "its name says it is optional"
    if source in ("assign", "quiz") and grade is not None and grade == 0:
        return False, "it is not graded"
    if source == "event" and modname in OPTIONAL_MODULES:
        return False, f"it is a {modname} activity"
    return True, ""


def prefs(engine: Engine, kind: str, ids: list[int] | None = None) -> dict[int, ItemPref]:
    with session(engine) as s:
        q = select(ItemPref).where(ItemPref.user_id == USER, ItemPref.kind == kind)
        rows = s.exec(q).all()
    if ids is not None:
        wanted = set(ids)
        return {p.item_id: p for p in rows if p.item_id in wanted}
    return {p.item_id: p for p in rows}


def set_pref(engine: Engine, kind: str, item_id: int, ignored: object = UNSET,
             criticality: object = UNSET, now: float | None = None) -> ItemPref | None:
    """Ignore / un-ignore an item, or set it mandatory, optional or back to automatic
    (``criticality=None``). Returns None when the item doesn't exist."""
    if kind not in KINDS:
        raise PrefError(f"kind must be one of {', '.join(KINDS)}")
    if ignored is not UNSET and not isinstance(ignored, bool):
        raise PrefError("ignored must be true or false")
    if criticality is not UNSET and criticality not in (None, "", *CRITICALITIES):
        raise PrefError("criticality must be mandatory, optional or null (automatic)")
    ts = int(now if now is not None else time.time())
    with session(engine) as s:
        if s.get(Deadline if kind == "deadline" else Section, item_id) is None:
            return None
        pref = s.exec(select(ItemPref).where(
            ItemPref.user_id == USER, ItemPref.kind == kind, ItemPref.item_id == item_id)).first()
        pref = pref or ItemPref(user_id=USER, kind=kind, item_id=item_id)
        if ignored is not UNSET:
            pref.ignored_at = (pref.ignored_at or ts) if ignored else None
        if criticality is not UNSET:
            pref.criticality = criticality or ""
        pref.updated_at = ts
        if pref.ignored_at is None and not pref.criticality:
            if pref.id is not None:
                s.delete(pref)
                s.commit()
            return ItemPref(user_id=USER, kind=kind, item_id=item_id, updated_at=ts)
        s.add(pref)
        s.commit()
        s.refresh(pref)
    return pref


def resolve(pref: ItemPref | None, auto: bool, reason: str = "") -> dict:
    """The fields every deadline / section carries in the API."""
    chosen = pref.criticality if pref and pref.criticality in CRITICALITIES else ""
    mandatory = chosen == "mandatory" if chosen else auto
    return {
        "mandatory": mandatory,
        "criticality": "mandatory" if mandatory else "optional",
        "criticality_by": "you" if chosen else "auto",
        "optional_reason": "" if chosen or mandatory else reason,
        "ignored": bool(pref and pref.ignored_at),
    }


def state(engine: Engine, kind: str, item_id: int) -> dict:
    """The resolved fields (``resolve``) of one deadline or section."""
    from app.models import Module

    with session(engine) as s:
        auto, reason = True, ""
        if kind == "deadline":
            d = s.get(Deadline, item_id)
            if d is not None:
                module = s.get(Module, d.module_id) if d.module_id else None
                auto, reason = auto_mandatory(d.source, d.name, d.grade,
                                              module.modname if module else "")
    return resolve(prefs(engine, kind, [item_id]).get(item_id), auto, reason)


def target_percent(engine: Engine) -> float:
    with session(engine) as s:
        row = s.get(CatchUpPrefs, USER)
    return row.target_percent if row else DEFAULT_TARGET


def set_target_percent(engine: Engine, value: float, now: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not MIN_TARGET <= value <= MAX_TARGET:
        raise PrefError(f"the target must be between {MIN_TARGET:g} and {MAX_TARGET:g} %")
    with session(engine) as s:
        row = s.get(CatchUpPrefs, USER) or CatchUpPrefs(user_id=USER)
        row.target_percent = round(float(value), 1)
        row.updated_at = int(now if now is not None else time.time())
        s.add(row)
        s.commit()
    return round(float(value), 1)
