"""ICS (iCalendar, RFC 5545) feed: deadlines and study entries in one calendar (breaks and
days off are left out), and its secret URL.

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


def _deadline_events(items: list[dict], stamp: str, alarms, base_url: str = "") -> list[str]:
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
        if base_url:
            desc.append(f"Open in Study Companion:\n{focus_url(base_url, d['due_at'])}")
        if d.get("course_name"):
            desc.append(d["course_name"])
        if d.get("url"):
            desc.append(f"On Moodle:\n{d['url']}")
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
            lines.append(f"DESCRIPTION:{_paras(desc)}")
        if d.get("url"):
            lines.append(f"URL:{d['url']}")
        if d.get("course_name"):
            lines.append(f"CATEGORIES:{_escape(d['course_name'])}")
        if not d.get("done") and d.get("mandatory", True):
            for lead in alarms:
                lines += _alarm(title, _lead(lead))
        lines.append("END:VEVENT")
    return lines


def focus_url(base_url: str, ts: int) -> str:
    """The web calendar opened on the entry (or deadline) at ``ts``."""
    return f"{base_url.rstrip('/')}/#/calendar?at={int(ts)}"


def _paras(paras: list[str]) -> str:
    """Paragraphs separated by a blank line, escaped for a DESCRIPTION."""
    return _escape("\n\n".join(paras))


def _block_events(blocks: list[dict], base_url: str, stamp: str, day_alarm: bool) -> list[str]:
    """One busy VEVENT per study entry, grouped by course like the web calendar and the
    printed weeks (``app.planner.groups``): "Spanish - Study", "Spanish - Test 1". The
    description starts with a link that opens the entry in Study Companion, on its own line,
    then each piece of work in its own paragraph (what to do, the files), then the Moodle
    links. With ``day_alarm``, the first entry of each day has an alarm at its start with
    the day's agenda."""
    lines: list[str] = []
    position: dict[str, int] = {}
    entries = groups.group(blocks)
    by_day: dict[str, list[dict]] = {}
    for g in entries:
        by_day.setdefault(g["date"], []).append(g)
    for g in entries:
        n = position[g["date"]] = position.get(g["date"], 0) + 1
        url = focus_url(base_url, g["start"]) if base_url else ""
        paras = [f"Open in Study Companion:\n{url}"] if url else []
        moodle: list[str] = []
        for b in g["blocks"]:
            title = b.get("title", "")
            if b.get("parts", 1) > 1:
                step = "review" if b.get("kind") == "recall" else "part"
                title += f" ({step} {b['part']}/{b['parts']})"
            para = [title]
            if b.get("detail"):
                para.append(b["detail"])
            files = b.get("files") or []
            if files:
                para.append("Files: " + ", ".join(
                    f["name"] + (f" ({f['pages']} p.)" if f.get("pages") else "") for f in files))
            paras.append("\n".join(para))
            if b.get("url") and b["url"] not in moodle:
                moodle.append(b["url"])
        if moodle:
            paras.append("On Moodle:\n" + "\n".join(moodle))
        lines += [
            "BEGIN:VEVENT",
            f"UID:schedule-{g['date']}-{n}@study-companion",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_dt(g['start'])}",
            f"DTEND:{_dt(g['end'])}",
            f"SUMMARY:{_escape(g['label'])}",
            f"DESCRIPTION:{_paras(paras)}",
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


def build_ics(items: list[dict], now: int | None = None, name: str = "Study Companion",
              alarms: tuple[int, ...] | list[int] = (1440,),
              blocks: list[dict] | None = None, base_url: str = "",
              day_alarm: bool = False) -> str:
    """The calendar feed: one VEVENT per deadline at its due time, with an alarm per lead
    time in ``alarms`` (minutes before) until it is done, and one per study entry of the
    published schedule. Breaks, unavailabilities and days off are not events: the feed only
    holds what you do (the web calendar and the PDF can show them)."""
    stamp = _dt(int(now if now is not None else time.time()))
    lines = _header(name)
    lines += _deadline_events(items, stamp, alarms, base_url)
    lines += _block_events(blocks or [], base_url, stamp, day_alarm)
    return _finish(lines)
