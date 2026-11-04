"""ICS (iCalendar, RFC 5545) export of deadlines, and the secret feed URL.

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

PRODID = "-//Study Companion//Deadlines//EN"


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


def build_ics(items: list[dict], now: int | None = None, name: str = "Study deadlines",
              alarms: tuple[int, ...] | list[int] = (1440,),
              sessions: list[dict] | None = None) -> str:
    """One VEVENT per deadline, at its due time, with an alarm per lead time in ``alarms``
    (minutes before) until it is done; plus one daily study reminder per ``sessions`` entry
    (``app.reminders.daily_sessions``) with an alarm at its start."""
    stamp = _dt(int(now if now is not None else time.time()))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
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
        if not d.get("done"):
            for lead in alarms:
                lines += _alarm(title, _lead(lead))
        lines.append("END:VEVENT")
    for sess in sessions or []:
        bits = []
        if sess.get("minutes"):
            bits.append(f"{_human(sess['minutes'])} planned")
        if sess.get("cards_due"):
            bits.append(f"{sess['cards_due']} card{'s' if sess['cards_due'] != 1 else ''} to review")
        title = "Study time" + (f": {', '.join(bits)}" if bits else "")
        length = max(int(sess.get("minutes") or 0), 15)
        lines += [
            "BEGIN:VEVENT",
            f"UID:study-{sess['date']}@study-companion",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_dt(sess['start'])}",
            f"DTEND:{_dt(sess['start'] + length * 60)}",
            f"SUMMARY:{_escape(title)}",
            "TRANSP:TRANSPARENT",
            "CATEGORIES:Study Companion",
        ]
        if sess.get("items"):
            lines.append(f"DESCRIPTION:{_escape(chr(10).join(sess['items']))}")
        lines += _alarm(title, "PT0M")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
