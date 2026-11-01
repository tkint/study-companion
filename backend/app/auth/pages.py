"""Minimal server-rendered pages for M0. The React UI replaces these in M2."""

from __future__ import annotations

from html import escape

_STYLE = """
:root { color-scheme: light dark; --accent: #2563eb; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
  padding: 16px; background: Canvas; color: CanvasText; }
main { width: 100%; max-width: 380px; }
h1 { font-size: 1.4rem; margin: 0 0 4px; }
p { margin: 0 0 16px; opacity: .8; }
label { display: block; font-weight: 600; margin-bottom: 6px; }
input, button { width: 100%; font-size: 16px; padding: 12px; border-radius: 10px; }
input { border: 1px solid #8886; background: transparent; color: inherit; margin-bottom: 12px; }
button { border: 0; background: var(--accent); color: #fff; font-weight: 600; cursor: pointer; }
.error { color: #dc2626; opacity: 1; }
.muted { font-size: .85rem; opacity: .6; margin-top: 16px; }
"""


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{escape(title)}</title>
<style>{_STYLE}</style>
</head>
<body><main>{body}</main></body>
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


def home_page(version: str) -> str:
    return _page(
        "Study Companion",
        f"""
<h1>Hello from Study Companion</h1>
<p>The server is up and you are signed in. Moodle sync arrives in the next release.</p>
<form method="post" action="/logout"><button type="submit">Sign out</button></form>
<p class="muted">Version {escape(version)}</p>""",
    )
