"""Server-rendered pages: login, settings and the basic sync status page (also the home page
when no web UI build is present). The React UI in frontend/ covers everything else."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

# Same design tokens as the React UI (frontend/src/styles.css), so these pages match it.
_TOKENS_DARK = """
  --bg: #0b0f17; --surface: #151b26; --text: #e5e7eb; --muted: #9ca3af; --border: #273042;
  --accent: #60a5fa; --accent-text: #0b0f17; --bad: #f87171; --bad-bg: #2a1215;
  --warn: #fbbf24; --warn-bg: #2a2110; --ok: #4ade80;
"""

_STYLE = (
    """
:root { color-scheme: light; --bg: #f6f7f9; --surface: #ffffff; --text: #111827;
  --muted: #6b7280; --border: #e5e7eb; --accent: #2563eb; --accent-text: #ffffff;
  --bad: #dc2626; --bad-bg: #fef2f2; --warn: #b45309; --warn-bg: #fffbeb; --ok: #15803d;
  --radius: 12px; --topbar: 56px; --tabbar: 60px;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark; """
    + _TOKENS_DARK
    + """ } }
:root[data-theme="dark"] { color-scheme: dark; """
    + _TOKENS_DARK
    + """ }
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--text); line-height: 1.45; }
a { color: var(--accent); text-decoration: none; } a:hover { text-decoration: underline; }
main { max-width: 760px; margin: 0 auto; padding: 24px 16px 48px; }
body.center { min-height: 100vh; display: flex; align-items: center; justify-content: center; }
body.center main { width: 100%; max-width: 400px; padding: 16px; }
h1 { font-size: 1.5rem; margin: 0 0 16px; }
p { margin: 0 0 12px; }
label { display: block; font-weight: 600; margin: 0 0 6px; }
input { display: block; width: 100%; font: inherit; font-size: 16px; padding: 11px 12px;
  border-radius: 10px; border: 1px solid var(--border); background: var(--bg); color: var(--text);
  margin: 0 0 14px; min-height: 44px; }
input:focus { outline: 2px solid var(--accent); outline-offset: 1px; border-color: transparent; }
button { display: inline-flex; align-items: center; justify-content: center; width: 100%;
  min-height: 44px; padding: 10px 16px; border-radius: 10px; border: 1px solid transparent;
  background: var(--accent); color: var(--accent-text); font: inherit; font-weight: 600;
  cursor: pointer; }
button:disabled { opacity: .55; cursor: default; }
button.secondary { background: transparent; color: var(--text); border-color: var(--border); }
button.danger { background: transparent; color: var(--bad); border-color: var(--bad); }
.error { color: var(--bad); }
.alert { border: 1px solid var(--bad); background: var(--bad-bg); border-radius: 10px; padding: 10px 12px; }
.ok { color: var(--ok); } .warn { color: var(--warn); }
.notice { border-radius: var(--radius); padding: 12px 14px; margin: 0 0 16px; border: 1px solid var(--border);
  background: var(--surface); }
.notice.ok { border-color: var(--ok); } .notice.error { border-color: var(--bad); background: var(--bad-bg); }
.muted { color: var(--muted); font-size: .88rem; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 18px; margin: 0 0 16px; }
.card h2 { font-size: 1.05rem; margin: 0 0 10px; overflow-wrap: anywhere; }
.card p { font-size: .92rem; }
.helper { border-left: 3px solid var(--accent); padding: 4px 0 4px 12px; margin: 0 0 14px; }
.helper ol { margin: 4px 0 8px; padding-left: 20px; font-size: .9rem; color: var(--muted); }
.helper p { margin: 0 0 4px; }
a[aria-disabled="true"] { opacity: .5; pointer-events: none; }
details { margin: 0 0 14px; } summary { cursor: pointer; margin-bottom: 10px; color: var(--muted); }
code { font-size: .85em; }
.row { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0 0; }
.row form { flex: 1 1 160px; margin: 0; }
.tag { display: inline-block; font-size: .72rem; padding: 1px 8px; border-radius: 99px;
  border: 1px solid var(--border); color: var(--muted); margin-left: 6px; vertical-align: middle; }
.footnote { text-align: center; color: var(--muted); font-size: .8rem; margin-top: 24px; }
/* top bar and tabs, as in the React UI */
.topbar { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 16px;
  min-height: var(--topbar); padding: 8px 16px; padding-top: max(8px, env(safe-area-inset-top));
  background: var(--surface); border-bottom: 1px solid var(--border); }
.brand { display: flex; align-items: center; gap: 8px; color: var(--text); font-weight: 700; }
.brand:hover { text-decoration: none; }
.tabs { display: flex; gap: 4px; margin-left: auto; }
.tabs a { display: flex; align-items: center; gap: 6px; padding: 8px 12px; border-radius: 10px;
  color: var(--muted); font-weight: 600; }
.tabs a:hover { text-decoration: none; background: var(--bg); }
.tabs a[aria-current="page"] { color: var(--accent); background: var(--bg); }
.tabs svg, .theme-switch svg { width: 20px; height: 20px; fill: none; stroke: currentColor;
  stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.theme-switch { display: inline-flex; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.theme-switch button { width: auto; min-height: 36px; padding: 6px 9px; background: transparent;
  color: var(--muted); border: 0; border-radius: 0; }
.theme-switch button[aria-pressed="true"] { background: color-mix(in srgb, var(--accent) 16%, transparent);
  color: var(--accent); }
.theme-switch svg { width: 18px; height: 18px; }
@media (max-width: 640px) {
  .theme-switch { margin-left: auto; }
  .tabs { position: fixed; left: 0; right: 0; bottom: 0; margin: 0; gap: 0; background: var(--surface);
    border-top: 1px solid var(--border); padding-bottom: env(safe-area-inset-bottom); z-index: 10; }
  .tabs a { flex: 1; flex-direction: column; gap: 2px; padding: 8px 0; font-size: .65rem;
    border-radius: 0; min-height: var(--tabbar); justify-content: center; }
  .tabs a[aria-current="page"] { background: transparent; }
  body.app main { padding-bottom: calc(var(--tabbar) + 32px + env(safe-area-inset-bottom)); }
}
"""
)

# Applied before paint: the theme picked in the web UI (stored per device), and the colour
# of the phone's status bar.
_THEME_JS = """<script>
(function () {
  function get() { try { var t = localStorage.getItem("theme"); return t === "light" || t === "dark" ? t : "system"; } catch (e) { return "system"; } }
  function apply(t) {
    var root = document.documentElement;
    if (t === "system") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", t);
    var dark = t === "dark" || (t === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.querySelectorAll('meta[name="theme-color"]').forEach(function (m) {
      m.setAttribute("content", dark ? "#151b26" : "#ffffff");
    });
    // Android takes the system bars' colour from the manifest, which reads this cookie.
    try {
      document.cookie = "theme=" + (t === "system" ? "; max-age=0" : t + "; max-age=31536000") +
        "; path=/; SameSite=Lax" + (location.protocol === "https:" ? "; Secure" : "");
    } catch (e) {}
    document.querySelectorAll(".theme-switch button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.theme === t));
    });
  }
  apply(get());
  document.addEventListener("DOMContentLoaded", function () {
    apply(get());
    document.querySelectorAll(".theme-switch button").forEach(function (b) {
      b.addEventListener("click", function () {
        try { if (b.dataset.theme === "system") localStorage.removeItem("theme"); else localStorage.setItem("theme", b.dataset.theme); } catch (e) {}
        apply(b.dataset.theme);
      });
    });
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { apply(get()); });
})();
</script>"""

_ICONS = {
    "today": '<path d="M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10"/>',
    "courses": '<path d="M4 5h7a3 3 0 013 3v12a2 2 0 00-2-2H4zM20 5h-5a3 3 0 00-3 3"/>',
    "study": '<path d="M4 7l8-4 8 4-8 4zM8 9v5c0 1.5 2 3 4 3s4-1.5 4-3V9M20 7v6"/>',
    "calendar": '<path d="M4 6h16v14H4zM4 10h16M9 3v5M15 3v5"/>',
    "prompt": '<path d="M4 5h16v11H9l-5 4zM8 9h8M8 12h5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    "light": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "system": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "dark": '<path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z"/>',
}


def _svg(name: str) -> str:
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{_ICONS[name]}</svg>'


def _topbar(active: str) -> str:
    # Same tabs, in the same order, as the React UI (frontend/src/App.tsx).
    tabs = [("today", "Today", "/#/"), ("courses", "Courses", "/#/courses"),
            ("study", "Study", "/#/study"), ("calendar", "Calendar", "/#/calendar"),
            ("prompt", "Prompt", "/#/prompt"), ("settings", "Settings", "/settings")]
    links = "".join(
        f'<a href="{href}"{" aria-current=\"page\"" if key == active else ""}>{_svg(key)}<span>{label}</span></a>'
        for key, label, href in tabs
    )
    themes = "".join(
        f'<button type="button" data-theme="{t}" aria-pressed="false" aria-label="{label}" title="{label}">{_svg(t)}</button>'
        for t, label in (("light", "Light theme"), ("system", "Use the device theme"), ("dark", "Dark theme"))
    )
    return f"""<header class="topbar">
<a class="brand" href="/#/"><img src="/favicon.svg" alt="" width="28" height="28"><span>Study Companion</span></a>
<nav class="tabs" aria-label="Main">{links}</nav>
<div class="theme-switch" role="group" aria-label="Theme">{themes}</div>
</header>"""


def _page(title: str, body: str, wide: bool = False, nav: str | None = None) -> str:
    """``nav`` (the active tab) adds the web UI's top bar; without it the page is a centred
    card (sign-in)."""
    header = _topbar(nav) if nav else ""
    body_class = "app" if nav else ("" if wide else "center")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#151b26" media="(prefers-color-scheme: dark)">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>{escape(title)}</title>
<style>{_STYLE}</style>
{_THEME_JS}
</head>
<body class="{body_class}">{header}<main>{body}</main></body>
</html>"""


def login_page(error: str | None = None) -> str:
    error_html = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    return _page(
        "Sign in · Study Companion",
        f"""
<div class="card">
<h1><img src="/favicon.svg" alt="" width="32" height="32" style="vertical-align:-7px;margin-right:8px">Study Companion</h1>
<p class="muted">Sign in to continue.</p>
{error_html}
<form method="post" action="/login">
  <label for="password">Password</label>
  <input id="password" name="password" type="password" autocomplete="current-password"
         required autofocus>
  <button type="submit">Sign in</button>
</form>
</div>""",
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
        "Sync details · Study Companion",
        f"""
<h1>Sync details</h1>
<div class="card">{status}
<div class="row">{sync_button}
<form method="post" action="/logout"><button type="submit" class="secondary">Sign out</button></form>
</div></div>
{courses_html}
<p class="footnote">Version {escape(version)}</p>""",
        wide=True,
        nav="today",
    )


LAUNCH_PATH = "/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=12345&urlscheme=moodlemobile"

_TOKEN_LINK_JS = """
<script>
(function () {
  var url = document.getElementById("url"), link = document.getElementById("token-link"),
      hint = document.getElementById("token-hint");
  if (!url || !link) return;
  function update() {
    var v = url.value.trim().replace(/\\/+$/, "").replace(/\\/(login\\/index\\.php|my|index\\.php)$/, "");
    var ok = /^https:\\/\\/[^\\/?#\\s]+(\\/[^?#\\s]*)?$/.test(v);
    link.href = ok ? v + "%s" : "#";
    if (ok) { link.removeAttribute("aria-disabled"); hint.textContent = ""; }
    else { link.setAttribute("aria-disabled", "true"); hint.textContent = "Enter the Moodle address first."; }
  }
  url.addEventListener("input", update);
  link.addEventListener("click", function (e) { if (link.getAttribute("href") === "#") e.preventDefault(); });
  update();
})();
</script>""" % LAUNCH_PATH


def _launch_url(site: str) -> str:
    """Moodle's app sign-in page, which hands out the token after SSO (see docs/moodle-token.md)."""
    from app.config import validate_moodle_url

    try:
        base = validate_moodle_url(site)
    except ValueError:
        return "#"
    return base + LAUNCH_PATH if base.startswith("https://") else "#"


def _connector_card(mcp_url: str, connections: list[dict]) -> str:
    if connections:
        items = "".join(
            f"<li>{escape(c['name'])} ({escape(', '.join(c['hosts']))}), last used "
            f"{_when(c['last_used_at'])}</li>"
            for c in connections
        )
        state = f"<p>Connected:</p><ul class=\"muted\">{items}</ul>"
        button = ('<form method="post" action="/settings/connector/disconnect">'
                  '<button type="submit" class="secondary">Disconnect all</button></form>')
    else:
        state, button = '<p class="muted">Not connected yet.</p>', ""
    return f"""<div class="card">
<h2>Claude connector</h2>
<p>On claude.ai open <em>Settings › Connectors › Add custom connector</em> and enter:</p>
<p><code>{escape(mcp_url)}</code></p>
{state}
<div class="row">{button}</div>
<p class="muted">Changing the password below also disconnects Claude. Guide: docs/connector.md.</p>
</div>"""


def settings_page(
    creds,
    *,
    message: str = "",
    error: str = "",
    moodle_error: str = "",
    url_value: str | None = None,
    version: str = "",
    mcp_url: str = "",
    connections: list[dict] | None = None,
) -> str:
    url_value = creds.url if url_value is None else url_value
    moodle_notice = (
        f'<p class="alert" role="alert">{escape(moodle_error)}</p>' if moodle_error else ""
    )
    notice = ""
    if message:
        notice += f'<p class="notice ok" role="status">{escape(message)}</p>'
    if error:
        notice += f'<p class="notice error" role="alert">{escape(error)}</p>'

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

    # Removing the token stops every sync until a new one is pasted: ask first.
    forget = (
        '<form method="post" action="/settings/moodle/forget" '
        'onsubmit="return confirm(\'Remove the saved Moodle token? Syncing stops until you paste a new one.\')">'
        '<button type="submit" class="danger">Remove saved token</button></form>'
        if creds.token or creds.token_unreadable
        else ""
    )
    return _page(
        "Settings · Study Companion",
        f"""
<h1>Settings</h1>
{notice}
<div class="card">
<h2>Moodle connection</h2>
{moodle_notice}
{token_state}
<form method="post" action="/settings/moodle" autocomplete="off">
  <label for="url">Moodle address</label>
  <input id="url" name="url" type="url" inputmode="url" required
         placeholder="https://moodle.your-university.ch" value="{escape(url_value)}">
  <div class="helper">
  <p><strong>Get your token (university SSO)</strong></p>
  <ol class="muted">
    <li>Use a computer browser (Chrome, Edge or Firefox) where you are signed in to Moodle.</li>
    <li>Open the link below. In the new tab press <strong>F12</strong> and open <em>Console</em>
      (reload the tab if the console is empty).</li>
    <li>Copy the whole <code>moodlemobile://token=…</code> link from the
      <em>Failed to launch</em> message and paste it in the Token field.</li>
  </ol>
  <p><a id="token-link" href="{escape(_launch_url(url_value))}" target="_blank" rel="noopener noreferrer"
     {'' if _launch_url(url_value) != '#' else 'aria-disabled="true"'}>Open the Moodle token page ↗</a>
     <span id="token-hint" class="muted">{'' if _launch_url(url_value) != '#' else 'Enter the Moodle address first.'}</span></p>
  </div>
  <label for="token">Token</label>
  <input id="token" name="token" type="password" autocomplete="off" spellcheck="false"
         placeholder="{"Leave empty to keep the saved token" if creds.token else "Paste the token or the moodlemobile:// link"}">
  <p class="muted">With university SSO, copy the token from Moodle's
  <em>Preferences › Security keys</em> page, or capture it from the Moodle app sign-in.
  More help: docs/moodle-token.md in the repository. Tokens can expire; paste a new one here
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
{_connector_card(mcp_url, connections or [])}
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
<div class="card">
<h2>Session</h2>
<p class="muted">Sign out on this device. <a href="/status">Sync details</a> lists what is stored per course.</p>
<form method="post" action="/logout"><button type="submit" class="secondary">Sign out</button></form>
</div>
<p class="footnote">Version {escape(version)}</p>
{_TOKEN_LINK_JS}""",
        wide=True,
        nav="settings",
    )


def consent_page(
    *,
    client_name: str,
    redirect_host: str,
    hidden: dict[str, str],
    signed_in: bool,
    error: str = "",
) -> str:
    """OAuth consent page for the MCP connector (claude.ai sends you here once)."""
    fields = "".join(
        f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">' for k, v in hidden.items()
    )
    error_html = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    password = "" if signed_in else """
  <label for="password">Study Companion password</label>
  <input id="password" name="password" type="password" autocomplete="current-password"
         required autofocus>"""
    name = escape(client_name or "An app")
    return _page(
        "Connect · Study Companion",
        f"""
<h1>Connect to Study Companion</h1>
<p><strong>{name}</strong> wants to read your courses, deadlines and course files.
After you allow it, you will be sent back to <strong>{escape(redirect_host)}</strong>.</p>
<p class="muted">Only allow this if you just added the connector yourself. You can disconnect
it at any time in Settings.</p>
{error_html}
<form method="post" action="/oauth/authorize">
  {fields}{password}
  <button type="submit" name="decision" value="allow">Allow</button>
  <div class="row"><button type="submit" name="decision" value="deny" class="secondary"
     formnovalidate>Cancel</button></div>
</form>""",
    )


def oauth_error_page(message: str) -> str:
    return _page(
        "Connection error · Study Companion",
        f"""
<h1>Can't connect</h1>
<p class="error" role="alert">{escape(message)}</p>
<p>Remove the connector in Claude and add it again. See docs/connector.md in the repository.</p>""",
    )
