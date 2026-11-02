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
.alert { border: 1px solid #dc2626; border-radius: 10px; padding: 10px 12px; }
a { color: var(--accent); }
details { margin: 0 0 12px; } summary { cursor: pointer; margin-bottom: 8px; }
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
            '<p class="warn">Moodle is not connected yet. Open <a href="/settings">Settings</a> '
            "and paste your Moodle token.</p>"
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
<form method="get" action="/settings"><button type="submit" class="secondary">Settings</button></form>
<form method="post" action="/logout"><button type="submit" class="secondary">Sign out</button></form>
</div>
{courses_html}
<p class="muted">Version {escape(version)}. The full web UI arrives in the next release.</p>""",
        wide=True,
    )


def settings_page(
    creds,
    *,
    message: str = "",
    error: str = "",
    moodle_error: str = "",
    url_value: str | None = None,
    version: str = "",
) -> str:
    url_value = creds.url if url_value is None else url_value
    moodle_notice = (
        f'<p class="error alert" role="alert">{escape(moodle_error)}</p>' if moodle_error else ""
    )
    notice = ""
    if message:
        notice += f'<p class="ok" role="status">{escape(message)}</p>'
    if error:
        notice += f'<p class="error" role="alert">{escape(error)}</p>'

    if creds.token_unreadable:
        token_state = (
            '<p class="warn">The saved token can no longer be read because SECRET_KEY changed. '
            "Paste it again.</p>"
        )
    elif creds.token:
        check = ""
        if creds.check_ok is False:
            check = f' <span class="warn">Last check failed: {escape(creds.check_message)}</span>'
        elif creds.check_message:
            check = f" {escape(creds.check_message)}."
        token_state = (
            f"<p>A token is saved (encrypted), updated {_when(creds.token_updated_at)}.{check}</p>"
        )
    else:
        token_state = '<p class="warn">No token saved yet.</p>'

    forget = (
        '<form method="post" action="/settings/moodle/forget">'
        '<button type="submit" class="secondary">Remove saved token</button></form>'
        if creds.token or creds.token_unreadable
        else ""
    )
    return _page(
        "Settings · Study Companion",
        f"""
<h1>Settings</h1>
<p><a href="/">← Back</a></p>
{notice}
<div class="card">
<h2>Moodle connection</h2>
{moodle_notice}
{token_state}
<form method="post" action="/settings/moodle" autocomplete="off">
  <label for="url">Moodle address</label>
  <input id="url" name="url" type="url" inputmode="url" required
         placeholder="https://moodle.your-university.ch" value="{escape(url_value)}">
  <label for="token">Token</label>
  <input id="token" name="token" type="password" autocomplete="off" spellcheck="false"
         placeholder="{"Leave empty to keep the saved token" if creds.token else "Paste the token or the moodlemobile:// link"}">
  <p class="muted">With university SSO, copy the token from Moodle's
  <em>Preferences › Security keys</em> page, or capture it from the Moodle app sign-in.
  Steps: docs/moodle-token.md in the repository. Tokens can expire; paste a new one here
  when the sync reports it.</p>
  <details><summary>No SSO? Sign in with username and password instead</summary>
  <p class="muted">Used once to get a token from Moodle; the password is not stored.</p>
  <label for="username">Moodle username</label>
  <input id="username" name="username" autocomplete="off">
  <label for="mpassword">Moodle password</label>
  <input id="mpassword" name="password" type="password" autocomplete="off">
  </details>
  <button type="submit">Test and save</button>
</form>
<div class="row">{forget}</div>
</div>
<div class="card">
<h2>Web UI password</h2>
<form method="post" action="/settings/password">
  <label for="current">Current password</label>
  <input id="current" name="current" type="password" autocomplete="current-password" required>
  <label for="new">New password (12+ characters)</label>
  <input id="new" name="new" type="password" autocomplete="new-password" minlength="12" required>
  <label for="confirm">Repeat new password</label>
  <input id="confirm" name="confirm" type="password" autocomplete="new-password" minlength="12" required>
  <button type="submit">Change password</button>
</form>
</div>
<p class="muted">Version {escape(version)}</p>""",
        wide=True,
    )
