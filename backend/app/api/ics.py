"""ICS (iCalendar, RFC 5545) feed: deadlines, study blocks and your unavailabilities in one
calendar, and its secret URL.

Phone and Outlook calendars subscribe to a URL and can't sign in, so the feed is protected
by a token in the query string (``/calendar.ics?token=...``). The token is an HMAC of
SECRET_KEY, the user id and a per-user epoch; "new link" bumps the epoch, which revokes the
old URL. Caddy strips ``token`` from its access log, and the app redacts it from uvicorn's.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone

from sqlalchemy.engine import Engine

from app.accounts import USER_ID
from app.db import session
from app.models import CalendarFeed
from app.planner import groups

PRODID = "-//Study Companion//Study calendar//EN"


def _epoch(engine: Engine, user_id: int = USER_ID) -> int:
    with session(engine) as s:
        feed = s.get(CalendarFeed, user_id)
        return feed.epoch if feed else 0


def feed_token(engine: Engine, secret_key: str, user_id: int = USER_ID) -> str:
    msg = f"ics:{user_id}:{_epoch(engine, user_id)}".encode()
    return hmac.new(secret_key.encode(), msg, hashlib.sha256).hexdigest()[:40]


def check_feed_token(engine: Engine, secret_key: str, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(feed_token(engine, secret_key), token or "")


def rotate_feed(engine: Engine, user_id: int = USER_ID, now: int | None = None) -> None:
    with session(engine) as s:
        feed = s.get(CalendarFeed, user_id) or CalendarFeed(user_id=user_id)
        feed.epoch += 1
        feed.created_at = int(now or time.time())
        s.add(feed)
        s.commit()


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
        .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "")
    )


def _fold(line: str) -> str:
    """Fold to 75 octets per line without splitting a UTF-8 character."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 75:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def _human(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h} h {m:02d}" if h and m else (f"{h} h" if h else f"{m} min")


def _dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _lead(minutes: int) -> str:
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    out = "-P" + (f"{days}D" if days else "")
    if hours or mins:
        out += "T" + (f"{hours}H" if hours else "") + (f"{mins}M" if mins else "")
    return out


def _alarm(text: str, trigger: str) -> list[str]:
    return ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(text)}",
            f"TRIGGER:{trigger}", "END:VALARM"]


def _header(name: str) -> list[str]:
    return [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]


def _finish(lines: list[str]) -> str:
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _deadline_events(items: list[dict], stamp: str, alarms) -> list[str]:
    lines: list[str] = []
    for d in items:
        if not d.get("due_at"):
            continue
        title = d["name"]
        if d.get("course_shortname"):
            title = f"{d['course_shortname']}: {title}"
        if d.get("done"):
            title = f"✓ {title}"
        desc = []
        if d.get("course_name"):
            desc.append(d["course_name"])
        if d.get("url"):
            desc.append(d["url"])
        lines += [
            "BEGIN:VEVENT",
            f"UID:{d['source']}-{d['id']}@study-companion",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_dt(d['due_at'])}",
            f"DTEND:{_dt(d['due_at'])}",
            f"SUMMARY:{_escape(title)}",
            "TRANSP:TRANSPARENT",
        ]
        if desc:
            lines.append(f"DESCRIPTION:{_escape(chr(10).join(desc))}")
        if d.get("url"):
            lines.append(f"URL:{d['url']}")
        if d.get("course_name"):
            lines.append(f"CATEGORIES:{_escape(d['course_name'])}")
        if not d.get("done") and d.get("mandatory", True):
            for lead in alarms:
                lines += _alarm(title, _lead(lead))
        lines.append("END:VEVENT")
    return lines


def _block_events(blocks: list[dict], base_url: str, stamp: str, day_alarm: bool) -> list[str]:
    """One busy VEVENT per study entry, grouped by course like the web calendar and the
    printed weeks (``app.planner.groups``): "Spanish - Study", "Spanish - Test 1". The
    description lists each block's work and material. With ``day_alarm``, the first entry of
    each day has an alarm at its start with the day's agenda."""
    base = base_url.rstrip("/")
    lines: list[str] = []
    position: dict[str, int] = {}
    entries = groups.group(blocks)
    by_day: dict[str, list[dict]] = {}
    for g in entries:
        by_day.setdefault(g["date"], []).append(g)
    for g in entries:
        n = position[g["date"]] = position.get(g["date"], 0) + 1
        first = g["blocks"][0]
        desc = []
        for b in g["blocks"]:
            title = b.get("title", "")
            if b.get("parts", 1) > 1:
                title += f" ({b['part']}/{b['parts']})"
            desc.append(f"- {title}" + (f": {b['detail']}" if b.get("detail") else ""))
            for f in b.get("files") or []:
                pages = f" ({f['pages']} p.)" if f.get("pages") else ""
                desc.append(f"  {f['name']}{pages}: {base}/#/file/{f['id']}"
                            + (f"?course={b['course_id']}" if b.get("course_id") else ""))
            if b.get("url"):
                desc.append(f"  On Moodle: {b['url']}")
        url = ""
        if first.get("course_id"):
            url = f"{base}/#/course/{first['course_id']}" + (
                f"?section={first['section_id']}" if first.get("section_id") else "")
        elif first.get("kind") == "flashcards":
            url = f"{base}/#/study?due=1"
        if url:
            desc.append(f"Open in Study Companion: {url}")
        lines += [
            "BEGIN:VEVENT",
            f"UID:schedule-{g['date']}-{n}@study-companion",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_dt(g['start'])}",
            f"DTEND:{_dt(g['end'])}",
            f"SUMMARY:{_escape(g['label'])}",
            f"DESCRIPTION:{_escape(chr(10).join(desc))}",
            "TRANSP:OPAQUE",
            f"CATEGORIES:{_escape(g.get('course_name') or 'Study Companion')}",
        ]
        if url:
            lines.append(f"URL:{url}")
        if day_alarm and n == 1:
            day = by_day[g["date"]]
            total = sum(x.get("minutes", 0) for x in day)
            agenda = (f"Study time: {_human(total)} planned, "
                      + ", ".join(x["label"] for x in day))
            lines += _alarm(agenda, "PT0M")
        lines.append("END:VEVENT")
    return lines


def _busy_events(busy: list[dict], stamp: str) -> list[str]:
    """Your unavailabilities (``app.planner.published.busy``), so the calendar shows why
    there is no study block there."""
    lines: list[str] = []
    for u in busy:
        title = u.get("reason") or "Unavailable"
        lines += [
            "BEGIN:VEVENT",
            f"UID:busy-{u['date']}-{u['start']}@study-companion",
            f"DTSTAMP:{stamp}",
        ]
        if u.get("all_day"):
            day = u["date"].replace("-", "")
            nxt = datetime.fromisoformat(u["date"]).date().toordinal() + 1
            lines += [f"DTSTART;VALUE=DATE:{day}",
                      f"DTEND;VALUE=DATE:{datetime.fromordinal(nxt):%Y%m%d}"]
        else:
            lines += [f"DTSTART:{_dt(u['start'])}", f"DTEND:{_dt(u['end'])}"]
        lines += [
            f"SUMMARY:{_escape(title)}",
            "DESCRIPTION:" + _escape("No study planned (Study Companion: when you can't study)."),
            "TRANSP:TRANSPARENT",
            "CATEGORIES:Unavailable",
            "END:VEVENT",
        ]
    return lines


def build_ics(items: list[dict], now: int | None = None, name: str = "Study Companion",
              alarms: tuple[int, ...] | list[int] = (1440,),
              blocks: list[dict] | None = None, base_url: str = "",
              busy: list[dict] | None = None, day_alarm: bool = False) -> str:
    """The calendar feed: one VEVENT per deadline at its due time, with an alarm per lead
    time in ``alarms`` (minutes before) until it is done; one per study block of the
    published schedule; and one per unavailability in ``busy``."""
    stamp = _dt(int(now if now is not None else time.time()))
    lines = _header(name)
    lines += _deadline_events(items, stamp, alarms)
    lines += _block_events(blocks or [], base_url, stamp, day_alarm)
    lines += _busy_events(busy or [], stamp)
    return _finish(lines)
