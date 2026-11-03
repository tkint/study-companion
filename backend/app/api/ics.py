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


def _dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(items: list[dict], now: int | None = None, name: str = "Study deadlines") -> str:
    """One VEVENT per deadline, at its due time, with a reminder a day before."""
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
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape(title)}",
                "TRIGGER:-P1D",
                "END:VALARM",
            ]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
