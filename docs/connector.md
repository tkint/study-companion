# Claude connector (MCP)

Study Companion includes a remote MCP server at `https://<DOMAIN>/mcp`. Once you add it as a
custom connector on claude.ai, Claude on the web, desktop and phone can read your courses,
deadlines and course files, and save summaries, practice questions and quiz results back to the
app, where you find them in the web UI. The app makes no AI calls itself: Claude does the work on your
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

The easiest way is the **Ask Claude** tab of the web UI: choose a course, a period and a goal
(catch-up summary, study plan, explain a topic, quiz, flashcards, exam prep, assignment, review
saved questions) and press **Copy**, then paste the prompt into a new Claude chat. The prompt names the exact tool
calls, so Claude reads only that material. Large periods are split into several prompts; paste
them one after the other. With **Save results to the app** on (the default), the prompt also
tells Claude which write tools to call, so summaries appear in the course page, questions become
flashcards in the **Study** tab and quiz scores are tracked.

You can also just ask, for example "Use Study Companion: what is due this week?" or
"Search my Linear Algebra course for eigenvalues and explain them".

### Tools

| Tool | What it returns |
| --- | --- |
| `list_courses(include_past)` | Courses with ids, language, sections/files/pages and deadline counts |
| `get_deadlines(course_id, from_date, to_date, include_done, page, mandatory_only, include_ignored)` | Assignments, quizzes and calendar events from today (or `from_date`) on, with done/overdue status and mandatory/optional; points to overdue mandatory work; leaves out what you ignored |
| `get_materials(course_id, from_date, to_date, section_from, section_to, page)` | Sections, activities and files with section ids, file ids and page counts (8 sections per page) |
| `get_section(section_id)` | One section in full: summary, activity descriptions, files, deadlines |
| `read_file(file_id, pages)` | Extracted text of a file for a page range like `"1-5"` (at most 20 pages per call) |
| `search_materials(query, course_id, page)` | Full-text search across files, section summaries and activities, with file and page references |
| `get_catch_up_plan(course_id, hours_per_day, days, from_date, include_optional, beyond_target)` | The app's rule-based plan for mandatory work: what upcoming deadlines need plus enough backlog to reach your catch-up goal, day by day with time estimates and file ids, and what is beyond the goal |
| `get_questions(course_id, section_id, due_only, page)` | Saved questions with their `question_id`, answer and review state (due first) |
| `ask_question(question, choices)` | Shows you one multiple-choice question as a card with clickable choices (see below) |

Write tools (they only change Claude's own notes in the app, never anything in Moodle):

| Tool | What it does |
| --- | --- |
| `save_summary(section_id, markdown, title)` | Saves a section summary in Markdown; it replaces that section's previous summary and shows in the course page |
| `save_questions(section_id, items)` | Saves up to 50 questions per call: `{question, answer, kind (short, mcq, flashcard), choices, explanation, source}`. Saving the same question again updates it. Returns the ids |
| `record_quiz_result(score, total, course_id, section_id, topic, items, notes)` | Records a quiz score; `items` (`[{question_id, correct}]`) also reschedules those saved questions |
| `log_study_time(minutes, course_id, note)` | Logs a study session (up to 12 h); it counts toward today's goal and streak on the **Study time** page |
| `trigger_sync()` | Starts a Moodle sync in the background |

`get_materials` and `get_section` show what is already saved for each section ("Saved in the
app: summary, 10 questions"), so Claude can skip work it already did. Claude may ask your permission before it runs a write
tool; you can allow it for the chat, or change the tool's permission in Claude's connector
settings.

Dates are `YYYY-MM-DD` in the server's `TIMEZONE` (default `Europe/Zurich`). Moodle does not date
sections, so a period selects the sections with a file uploaded or a deadline in it; when a course
was copied from an earlier year and nothing is dated in the period, the tool says so and lists the
whole course (or the section range).

### Clickable quiz questions

In a quiz ("Quiz me", "Review saved questions"), Claude asks each multiple-choice question with
`ask_question`. The app shows it as a small card under Claude's message, with one button per
choice. Tap a choice and it is sent as your answer (for example "B) The mitochondrion"), so
you don't have to type the letter and press send. Claude then corrects it as usual.

The card is an [MCP App](https://modelcontextprotocol.io/extensions/apps/overview): a sandboxed
page served by the connector, with no access to anything outside the chat. Support depends on
the chat app:

| Client | Clickable choices |
| --- | --- |
| Claude (web and desktop) | Yes |
| ChatGPT (developer mode connectors) | Yes, where its apps support MCP Apps |
| Gemini, and clients without MCP Apps | No: `ask_question` tells the assistant to present the question its own way, using the app's own quiz or clickable-choice format if it has one, or else lettered choices you answer by letter |

The connector learns whether the client shows MCP Apps when it connects. If you see no card,
or tapping a choice does nothing, the card says so and you can still type the letter. You can
also just say "write the choices in the chat" if you prefer.

### Text extraction

After each sync the server extracts text from PDF (per page), PowerPoint (per slide, with speaker
notes), Word, HTML pages and text files, and indexes it with SQLite FTS5 (accents ignored).
Scanned PDFs without a text layer have no text (no OCR). To redo it by hand:

```bash
docker compose exec app python -m app.cli extract          # new and changed files
docker compose exec app python -m app.cli extract --force  # every file again
```

## Gemini and ChatGPT (optional)

Only Claude is allowed by default. To use the same server from Gemini or ChatGPT, add its
callback host to the `OAUTH_REDIRECT_HOSTS` variable in GitHub (the list replaces the default, so
keep the Claude hosts) and run the Deploy workflow:

```
OAUTH_REDIRECT_HOSTS=claude.ai,claude.com,localhost,127.0.0.1,oauth-redirect.googleusercontent.com,oauth-redirect-sandbox.googleusercontent.com,oauth-redirect-test.googleusercontent.com,chatgpt.com
```

| Client | Host to add | Callback it registers |
|---|---|---|
| Gemini | `oauth-redirect.googleusercontent.com`, `oauth-redirect-sandbox.googleusercontent.com` and `oauth-redirect-test.googleusercontent.com` (all three: Gemini registers one callback on each, and one missing host refuses the whole registration) | `https://oauth-redirect*.googleusercontent.com/r/user_bound_custom-mcp-...` |
| ChatGPT | `chatgpt.com` | `https://chatgpt.com/connector_platform_oauth_redirect` |

Then add a custom connector in that app with the URL `https://<DOMAIN>/mcp`, leave the client ID
and secret empty (the app registers itself), and approve it on the Study Companion page with your
password, as for Claude. ChatGPT needs developer mode, where your plan offers it. The prompts in
the web UI are written for Claude but name the same tools, so they work there too. Remove a host
from the list to stop new connections from that app; **Disconnect all** signs out existing ones.

## Security

- The connector uses OAuth 2.1: discovery (`/.well-known/oauth-protected-resource` and
  `/.well-known/oauth-authorization-server`), dynamic client registration, the authorization code
  flow with PKCE (S256 only), refresh token rotation and revocation.
- You approve each new connection on the app's own page with your password. Redirects are only
  allowed to the hosts in `OAUTH_REDIRECT_HOSTS` (default `claude.ai, claude.com, localhost,
  127.0.0.1`; Gemini and ChatGPT only if you add them), so a code can't be sent elsewhere. Anyone can register a client, but nobody gets a token without your password.
- Access tokens last one hour (`OAUTH_ACCESS_TTL`), refresh tokens 30 days of inactivity
  (`OAUTH_REFRESH_TTL`). Tokens and codes are stored only as SHA-256 hashes.
- **Settings › Claude connector › Disconnect all** signs every client out. Changing the web UI
  password does too. Reconnect from Claude's connector settings afterwards.
- Course text you ask about is sent to Anthropic by Claude (or to Google by Gemini, OpenAI by ChatGPT), like anything
  else you paste in a chat.

## Troubleshooting

- **"Couldn't connect" on claude.ai:** open `https://<DOMAIN>/.well-known/oauth-authorization-server`
  in a browser; it should show JSON with your domain. If it shows `http://` or another host, check
  the `DOMAIN` variable in GitHub and run the Deploy workflow again.
- **"Can't connect: unknown client" on the approval page:** the registration was lost (database
  reset). Remove the connector in Claude and add it again.
- **"redirect URI not allowed"** (Gemini: "The Google redirect URL was rejected by the server"):
  the client's callback host is not in `OAUTH_REDIRECT_HOSTS`. The app log
  (`docker compose logs app | grep "registration refused"`) names the host it sent. Add it
  only if you trust it, then `docker compose up -d`.
- **Claude says a file has no text:** it is scanned, a video, or not extracted yet (next sync, or
  run `python -m app.cli extract`).
- **Testing without Claude:** the [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
  (`npx @modelcontextprotocol/inspector`) can connect to `https://<DOMAIN>/mcp` with "Streamable
  HTTP" and runs the same OAuth flow through a `localhost` callback.
