# Claude connector (MCP)

Study Companion includes a remote MCP server at `https://<DOMAIN>/mcp`. Once you add it as a
custom connector on claude.ai, Claude on the web, desktop and phone can read your courses,
deadlines and course files. The app makes no AI calls itself: Claude does the work on your
subscription, and fetches only what you ask about.

## Add the connector (once)

1. Make sure the app is reachable at `https://<DOMAIN>` (see [server-setup.md](server-setup.md))
   and has synced at least once.
2. On [claude.ai](https://claude.ai), open **Settings › Connectors** (on Team or Enterprise plans
   an owner may have to allow custom connectors first) and choose **Add custom connector**.
3. Name it `Study Companion` and enter the URL `https://<DOMAIN>/mcp`. Leave the advanced
   OAuth fields empty: the app supports dynamic client registration.
4. Click **Connect**. A Study Companion page opens and asks you to allow Claude; enter your web UI
   password if you are not signed in, then click **Allow**. You are sent back to Claude.
5. The connector now shows its tools. It is linked to your Claude account, so it also appears in
   the Claude apps on your phone and computer. In a chat, turn it on from the tools menu (the
   **+** / sliders button) if it is not on already.

The Settings page of the app shows the exact URL to paste and which clients are connected.

## Use it

The easiest way is the **Prompt** tab of the web UI: choose a course, a period and a goal
(catch-up summary, study plan, explain a topic, quiz, flashcards, exam prep, assignment) and
press **Copy**, then paste the prompt into a new Claude chat. The prompt names the exact tool
calls, so Claude reads only that material. Large periods are split into several prompts; paste
them one after the other.

You can also just ask, for example "Use Study Companion: what is due this week?" or
"Search my Linear Algebra course for eigenvalues and explain them".

### Tools

| Tool | What it returns |
| --- | --- |
| `list_courses(include_past)` | Courses with ids, language, sections/files/pages and deadline counts |
| `get_deadlines(course_id, from_date, to_date, include_done, page)` | Assignments, quizzes and calendar events in a date range, with done/overdue status |
| `get_materials(course_id, from_date, to_date, section_from, section_to, page)` | Sections, activities and files with section ids, file ids and page counts (8 sections per page) |
| `get_section(section_id)` | One section in full: summary, activity descriptions, files, deadlines |
| `read_file(file_id, pages)` | Extracted text of a file for a page range like `"1-5"` (at most 20 pages per call) |
| `search_materials(query, course_id, page)` | Full-text search across files, section summaries and activities, with file and page references |

All tools are read-only. Saving summaries and questions back to the app comes in M4.

Dates are `YYYY-MM-DD` in the server's `TIMEZONE` (default `Europe/Zurich`). Moodle does not date
sections, so a period selects the sections with a file uploaded or a deadline in it; when a course
was copied from an earlier year and nothing is dated in the period, the tool says so and lists the
whole course (or the section range).

### Text extraction

After each sync the server extracts text from PDF (per page), PowerPoint (per slide, with speaker
notes), Word, HTML pages and text files, and indexes it with SQLite FTS5 (accents ignored).
Scanned PDFs without a text layer have no text (no OCR). To redo it by hand:

```bash
docker compose exec app python -m app.cli extract          # new and changed files
docker compose exec app python -m app.cli extract --force  # every file again
```

## Security

- The connector uses OAuth 2.1: discovery (`/.well-known/oauth-protected-resource` and
  `/.well-known/oauth-authorization-server`), dynamic client registration, the authorization code
  flow with PKCE (S256 only), refresh token rotation and revocation.
- You approve each new connection on the app's own page with your password. Redirects are only
  allowed to the hosts in `OAUTH_REDIRECT_HOSTS` (default `claude.ai, claude.com, localhost,
  127.0.0.1`), so a code can't be sent elsewhere.
- Access tokens last one hour (`OAUTH_ACCESS_TTL`), refresh tokens 30 days of inactivity
  (`OAUTH_REFRESH_TTL`). Tokens and codes are stored only as SHA-256 hashes.
- **Settings › Claude connector › Disconnect all** signs every client out. Changing the web UI
  password does too. Reconnect from Claude's connector settings afterwards.
- Course text you ask about is sent to Anthropic by Claude, like anything else you paste in a chat.

## Troubleshooting

- **"Couldn't connect" on claude.ai:** open `https://<DOMAIN>/.well-known/oauth-authorization-server`
  in a browser; it should show JSON with your domain. If it shows `http://` or another host, check
  `DOMAIN` in `.env` and restart (`docker compose up -d`).
- **"Can't connect: unknown client" on the approval page:** the registration was lost (database
  reset). Remove the connector in Claude and add it again.
- **"redirect URI not allowed":** a client other than Claude tried to register. Add its host to
  `OAUTH_REDIRECT_HOSTS` only if you trust it.
- **Claude says a file has no text:** it is scanned, a video, or not extracted yet (next sync, or
  run `python -m app.cli extract`).
- **Testing without Claude:** the [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
  (`npx @modelcontextprotocol/inspector`) can connect to `https://<DOMAIN>/mcp` with "Streamable
  HTTP" and runs the same OAuth flow through a `localhost` callback.
