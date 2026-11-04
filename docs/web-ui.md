# Using the web UI

Open `https://<DOMAIN>` and sign in with your app password. The UI is built for phones first:
on a narrow screen the tabs (**Today**, **Courses**, **Calendar**, **Prompt**, **Settings**) sit at the bottom.

The sun / screen / moon buttons in the top bar pick a light theme, the device's theme
(default) or a dark theme. The choice is remembered on each device and also applies to the
Settings and sign-in pages. **Settings** is where you change the Moodle token and the app
password, and sign out. Removing the saved token asks for confirmation first.

## Add it to your home screen

- **iPhone (Safari):** Share → *Add to Home Screen*.
- **Android (Chrome):** menu → *Install app* (or *Add to Home screen*).

It then opens full screen like an app. It still needs the network: course data and files are
never stored on the phone (only the app's own code is cached, so it starts quickly).

## Today (dashboard)

- **Overdue**: past due, not done, from courses you're enrolled in, due in the last 120 days.
- **Due in the next 7 days** and **Later**: everything still ahead.
- **Mark done** hides an item from *Overdue* when Moodle doesn't track it (for example you
  handed it in on paper). **Undo** reverts it. Items Moodle already marks complete show
  *done in Moodle*. Your marks survive every resync.
- **Study today**: today's part of the catch-up plan (below) and how many flashcards are due.
  **Full plan** opens the whole plan.
- **Sync now** fetches from Moodle; the page refreshes when the sync ends.
- **Catch-up progress**: per course, the share of activities you completed, out of those
  Moodle tracks completion for (Moodle's own course progress when it reports one).

All times are shown in your device's time zone.

## Courses

The **Courses** tab lists every enrolled course with its progress. Type in the search field
to filter by name or short name (accents and case don't matter, so `algebre` finds
*Algèbre linéaire*). Each course lists its open deadlines, then its sections with activities and files.

- **PDFs** open in the built-in viewer (pinch or −/+ to zoom, ⤓ to download).
- **Images and text files** open in a new tab; **everything else** (Word, PowerPoint, HTML…)
  downloads, so it opens in the right app on your phone. Course HTML is never rendered by
  the site itself, for safety.
- Files Moodle marks as too large (videos, over `MOODLE_MAX_FILE_MB`) aren't kept on the
  server: use the *open in Moodle* link.

Each course also has a **Study** box (its summaries, questions and quiz results) and, in every
section:

- **Claude's notes**: the summary Claude saved with `save_summary`, rendered from Markdown
  (headings, lists, tables). Long notes fold; **Delete** removes one. Notes of a section that
  disappeared from Moodle are kept at the bottom of the page.
- **Review N cards** opens the section's flashcards; **Mark as studied** takes the section off
  the catch-up plan (tap again to undo).
- **Quiz results**: the scores Claude recorded with `record_quiz_result` and your flashcard
  sessions, newest first.

## Study (flashcards)

The **Study** tab lists your courses with saved questions and how many are due.
**Review** shows one card at a time: think of the answer, tap **Show answer** (for multiple
choice, tap your choice), then grade yourself:

| Button | Next review |
| --- | --- |
| **Again** | in 10 minutes (the card comes back at the end of the session) |
| **Hard** | about 1.2 × the last interval, at least a day |
| **Good** | 1 day, then 3 days, then the interval × 2.5 |
| **Easy** | 4 days, then 6, then longer than *Good* |

This is a simple form of spaced repetition (SM-2): cards you know come back less and less often,
cards you miss come back soon. When a session ends, its score is saved as a quiz result.
**Practise all** goes through every card of the course or section, due or not. When Claude
quizzes you and calls `record_quiz_result` with the question ids, those cards are rescheduled
the same way (right = *Good*, wrong = *Again*).

## Catch-up plan

Open it from **Today › Full plan**. It is built by rules, without AI:

1. **What is left**: every non-empty section of your enrolled courses that Moodle doesn't show as
   completed and you haven't marked studied, plus open assignments, quizzes and events.
2. **Time**: reading time from page counts (about 3 minutes per PDF page, 1.5 per slide, 4 per
   Word/HTML part, at least 15 minutes per section); 2 h per assignment, 45 min per quiz.
3. **Order**: by the date each item is needed by (a deadline's due date; for a section, the
   earliest open deadline in it or in a later section of the same course), then by grade
   weight, then section order, so courses without deadlines take turns.
4. **Days**: the items are laid out from today within your **hours per day** (saved, and used
   by Claude's `get_catch_up_plan` too). Long items are split over days. Items that only fit
   after their deadline are marked *late*; what doesn't fit in the chosen days is listed at the
   end.

**Mark studied** on a section removes it from the plan.

## Calendar and ICS export

The **Calendar** tab shows deadlines in month, week and list views (list by default on a
phone). Tap an item for details and *Mark done*.

To see deadlines in your phone or Outlook calendar, tap **Show subscription link**:

- **iPhone:** tap **Subscribe on this device** and confirm.
- **Google Calendar** (shows on Android): on a computer, *Settings → Add calendar → From URL*,
  paste the link.
- **Outlook:** *Add calendar → Subscribe from web*, paste the link.

Calendar apps refresh subscriptions on their own schedule (from every few minutes to about
a day). Each event has a reminder one day before the deadline; done items are prefixed ✓.

The link contains a private token, so anyone with it can read your deadline titles (nothing
else). If it leaks, tap **New link**: the old one stops working at once and you subscribe
again with the new one. The token is stripped from Caddy's and the app's logs.
**Download .ics** gives a one-off file instead, if you'd rather import than subscribe.

## Prompt

Builds a ready-to-paste prompt for Claude (with the connector from
[connector.md](connector.md) turned on):

- **Course**: one or more. **Period**: last 2 months, last 4 weeks, until the next deadline,
  the whole course, your own dates, or a section range (one course only).
- **Goal**: catch-up summary, study plan, explain a topic, quiz me, flashcards, exam prep,
  understand an assignment, or review saved questions. **Depth**, **time available** and the **language** of the answers
  (by default the course's language).
- **Save results to the app** (on by default) adds the write tool calls to the prompt, so
  Claude saves its summaries, questions and quiz scores where the course page and the Study tab
  show them.
- The preview counts the sections, files and pages that match. Large periods are split into
  several prompts so Claude stays within its limits; copy and paste them one after the other.

### Editing the prompt templates

Each goal comes from a Markdown template. To change its wording, open **Settings › Prompt
templates** (or *Edit the templates* on the prompt builder page), pick a goal and edit the text.
The editor checks it as you type and only saves a template that still works: the front matter
(title, description, order, topic) closes, `{{steps}}` is kept, only known placeholders and
`{{#option}}…{{/option}}` sections are used, and anything written like a call, `name(…)`, is a
real Study Companion tool. **Reset to built-in** goes back to the default.

Your edits are stored in the database (so they are in the backups and survive updates); the
built-in templates stay the Markdown files in `backend/app/prompts/` (placeholders are documented
in `backend/app/prompts/__init__.py`). When an app update changes a built-in template you edited,
the editor says so and shows the new built-in text next to yours.
