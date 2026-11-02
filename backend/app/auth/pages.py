"""Minimal server-rendered pages (login, sync status). The React UI replaces these in M2."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

_STYLE = """
:root { color-scheme: light dark; --accent: #2563eb; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
  padding: 16px; background: Canvas; color: CanvasText; }
main { width: 100%; max-width: 380px; }
main.wide { max-width: 720px; align-self: flex-start; }
h1 { font-size: 1.4rem; margin: 0 0 4px; }
p { margin: 0 0 16px; opacity: .8; }
label { display: block; font-weight: 600; margin-bottom: 6px; }
input, button { width: 100%; font-size: 16px; padding: 12px; border-radius: 10px; }
input { border: 1px solid #8886; background: transparent; color: inherit; margin-bottom: 12px; }
button { border: 0; background: var(--accent); color: #fff; font-weight: 600; cursor: pointer; }
.error { color: #dc2626; opacity: 1; }
.muted { font-size: .85rem; opacity: .6; margin-top: 16px; }
.card { border: 1px solid #8884; border-radius: 12px; padding: 12px 14px; margin: 0 0 12px; }
.card h2 { font-size: 1rem; margin: 0 0 4px; overflow-wrap: anywhere; }
.card p { margin: 0; font-size: .9rem; }
.row { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0 16px; }
.row form { flex: 1 1 140px; }
.tag { display: inline-block; font-size: .75rem; padding: 1px 8px; border-radius: 99px;
  border: 1px solid #8886; margin-left: 4px; vertical-align: middle; }
.ok { color: #16a34a; opacity: 1; } .warn { color: #d97706; opacity: 1; }
button.secondary { background: transparent; color: inherit; border: 1px solid #8886; }
"""


def _page(title: str, body: str, wide: bool = False) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{escape(title)}</title>
<style>{_STYLE}</style>
</head>
<body><main{' class="wide"' if wide else ""}>{body}</main></body>
</html>"""


def login_page(error: str | None = None) -> str:
    error_html = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    return _page(
        "Sign in · Study Companion",
        f"""
<h1>Study Companion</h1>
<p>Sign in to continue.</p>
{error_html}
<form method="post" action="/login">
  <label for="password">Password</label>
  <input id="password" name="password" type="password" autocomplete="current-password"
         required autofocus>
  <button type="submit">Sign in</button>
</form>""",
    )


def _when(ts: int | None) -> str:
    if not ts:
        return "never"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _mb(n: int) -> str:
    return f"{n / 1e6:.1f} MB"


def home_page(
    version: str,
    *,
    configured: bool = False,
    running: bool = False,
    last_run=None,
    overview: list[dict] | None = None,
) -> str:
    overview = overview or []
    if not configured:
        status = (
            '<p class="warn">Moodle is not connected yet. Set <code>MOODLE_URL</code> and '
            "<code>MOODLE_TOKEN</code> in <code>.env</code> (see docs/moodle-token.md), "
            "then restart the app.</p>"
        )
    elif running:
        status = '<p>Sync in progress… refresh in a minute.</p>'
    elif last_run is None:
        status = "<p>No sync yet. The first one starts a couple of minutes after start-up.</p>"
    else:
        cls = {"ok": "ok", "partial": "warn"}.get(last_run.status, "error")
        status = (
            f'<p class="{cls}">Last sync {escape(last_run.status)} at '
            f"{_when(last_run.finished_at or last_run.started_at)}: {last_run.courses} courses, "
            f"{last_run.files_downloaded} files downloaded, {last_run.files_unchanged} unchanged, "
            f"{last_run.files_failed} failed, {last_run.deadlines} deadlines.</p>"
        )
        if last_run.message:
            status += f'<p class="muted">{escape(last_run.message)}</p>'

    sync_button = (
        '<form method="post" action="/sync"><button type="submit"'
        + (" disabled" if running or not configured else "")
        + ">Sync now</button></form>"
    )
    cards = []
    for c in overview:
        lang = (
            f'<span class="tag" title="language from {escape(c["lang_source"])}">'
            f'{escape(c["lang"])}</span>' if c["lang"] else ""
        )
        extra = []
        if c["files_skipped"]:
            extra.append(f'{c["files_skipped"]} too large')
        if c["files_error"]:
            extra.append(f'<span class="warn">{c["files_error"]} failed</span>')
        cards.append(
            f"""<div class="card"><h2>{escape(c["fullname"] or c["shortname"])}{lang}</h2>
<p>{c["files_ok"]}/{c["files_total"]} files on the server ({_mb(c["bytes_ok"])})
{"· " + ", ".join(extra) if extra else ""}</p>
<p>{c["deadlines_upcoming"]} upcoming deadlines · {c["deadlines_past"]} past ·
synced {_when(c["synced_at"])}</p></div>"""
        )
    courses_html = "".join(cards) or '<p class="muted">No courses synced yet.</p>'
    return _page(
        "Study Companion",
        f"""
<h1>Study Companion</h1>
{status}
<div class="row">{sync_button}
<form method="post" action="/logout"><button type="submit" class="secondary">Sign out</button></form>
</div>
{courses_html}
<p class="muted">Version {escape(version)}. The full web UI arrives in the next release.</p>""",
        wide=True,
    )
