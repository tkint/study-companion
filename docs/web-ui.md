# Using the web UI

Open `https://<DOMAIN>` and sign in with your app password. The UI is built for phones first:
on a narrow screen the tabs (**Today**, **Courses**, **Study**, **Calendar**, **Ask Claude**, **Settings**)
sit at the bottom.

## Finding your way

Each tab is a section. When a section has more than one page, its pages show as a row of pills
at the top of the page, with the current one highlighted:

| Tab | Pages |
| --- | --- |
| Today | Overview · Catch-up plan · Schedule |
| Courses | All courses (a course and its files open from there) |
| Study | Flashcards · Study time |
| Calendar | Calendar, reminders and the phone subscription |
| Ask Claude | Prompt builder · Templates |

The browser tab shows where you are too ("Schedule · Today · Study Companion"). On your first
visit a short **tour** walks through the sections; the **?** button in the top bar plays it
again at any time.

The sun / screen / moon buttons in the top bar pick a light theme, the device's theme
(default) or a dark theme. The choice is remembered on each device and also applies to the
Settings and sign-in pages. **Settings** is where you change the Moodle token and the app
password, and sign out. Removing the saved token asks for confirmation first.

## Add it to your home screen

- **iPhone (Safari):** Share → *Add to Home Screen*.
- **Android (Chrome):** menu → *Install app* (or *Add to Home screen*).

It then opens full screen like an app. It still needs the network: course data and files are
never stored on the phone (only the app's own code is cached, so it starts quickly).

The phone's status and navigation bars follow the theme. On Android, Chrome colours them from
the app's manifest, which it only re-reads now and then (when you open the app, at most about
once a day): after switching theme, close and reopen the app, and if a bar stays white, remove
the app from the home screen and install it again.

## Today (dashboard)

The home page leads with what you did, not with what is left:

- **Greeting and week strip**: one dot per day of the last 7, filled on the days you studied.
  A *study day* is any day you marked a deadline done, marked a section studied, reviewed a
  flashcard, took a quiz (in Claude or here) or Claude saved a summary for you (days follow
  `TIMEZONE`). The ring shows your average course progress.
- **Wins**: your streak (study days in a row; a streak that ended yesterday still counts until
  the end of today), what you got done this week, cards reviewed and your quiz average.
- **Today's plan**: today's part of the catch-up plan (below) and how many flashcards are due.
  **Studied** takes a section off the plan. **Full plan** opens the whole plan.
- **Coming up**: the next items due in 7 days; **Show more** adds the rest of the week and later.
- **Past items to catch up on** (folded): past due, not done, from courses you're enrolled in,
  due in the last 120 days. Open it when you want to.
- **Done** marks an item done when Moodle doesn't track it (for example you handed it in on
  paper). **Undo** reverts it. Items Moodle already marks complete show *done in Moodle*.
  Your marks survive every resync.
- **Sync now** (top right) fetches from Moodle; the page refreshes when the sync ends.
- **Your courses**: per course, the share of activities you completed, out of those Moodle
  tracks completion for (Moodle's own course progress when it reports one).

Little wins (a deadline done, a section studied, a review session finished) get a confetti
burst. With *reduce motion* turned on in your device settings, animations and confetti are off.

All times are shown in your device's time zone.

## Courses

The **Courses** tab lists every enrolled course with its progress. Type in the search field
to filter by name or short name (accents and case don't matter, so `algebre` finds
*Algèbre linéaire*). Each course lists its upcoming deadlines (tick **Show past** for the
earlier ones, **Show ignored** for what you let go), then its sections with activities and files.

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

## Study time

Open it from **Study › Study time** (`#/time`). Tap **Start the timer** when you sit down
(pick a course or leave *General study*) and **Stop and save** when you're done; the timer
keeps running if you close the app or lock your phone, since only its start time is kept on
the device. Forgot the timer? **Add time by hand**. When Claude runs a study session or a
quiz from the prompt builder, it asks how long you studied and logs it with `log_study_time`.

The page shows today against your daily goal (the catch-up plan's **hours per day**), this
week (from Monday), your streak of days in a row, the last 14 days as a chart (green bars: goal
reached), time per course over the last 7 days, and your recent sessions (✕ deletes one). Days
follow the server's `TIMEZONE`.

## Reminders

There is no push service: reminders arrive as alarms in the calendar feed you subscribe to (see
below), so your phone notifies you like any other calendar event. Set them on the **Calendar**
page under **Reminders**:

- **Before each deadline**: up to 3 alarms (1 week, 2 days, 1 day, 2 hours, 1 hour; default
  1 day and 2 hours). Done and optional deadlines have no alarm; ignored ones aren't in the feed.
- **Daily study reminder** (on by default, 18:00): a "Study time" event for today and the next
  6 days, at your chosen time, with the minutes the catch-up plan gives that day, its items in
  the description, and today's flashcards to review. Days with nothing planned have no event.

The **Study** page also shows a short card for today: cards to review, deadlines in the next
48 hours, and what you studied against what's planned.

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

### Mandatory, optional and ignored work

You won't catch up on everything, so the plan focuses on what is **mandatory**:

- A deadline counts as **optional** when its name says so (*optional, facultatif, bonus,
  fakultativ, freiwillig, practice, entraînement, self-test…*), when it is an assignment or quiz
  graded out of 0, or when it is a feedback, choice, forum or survey activity. Everything else,
  and every section, is mandatory. The ⋯ button on a deadline or section (course page, plan)
  lets you **Mark as optional** / **Mark as mandatory** when the guess is wrong.
- **Ignore (let it go)** in the same menu takes past work you decided to skip off the plan,
  the home page, the calendar feed and your goal. **Stop ignoring** brings it back.
- Optional work is left out of the plan; tick **Include optional work** to plan it too.

### Your catch-up goal

**Catch-up goal** (40 to 100 %, 60 % by default) is the share of the mandatory work you aim
to catch up. Progress counts every mandatory section plus the mandatory deadlines of the last
120 days (minus those closed in Moodle), weighted by their estimated time: sections marked
studied or complete in Moodle and deadlines done count as caught up. The bar on the plan shows
where you are and the mark is your goal.

The plan always keeps the work upcoming deadlines need, then adds the backlog (overdue items
and sections no upcoming deadline needs) in priority order until it reaches your goal. The rest
is listed under **Beyond your goal** (only if you have time); tick **Plan beyond my goal** to
schedule it anyway. Claude's `get_catch_up_plan` and the prompts use the same goal.

## Study schedule (timed blocks and .ics)

**Catch-up plan › Timed schedule** turns the plan into focus blocks with start and end times,
built by rules, without AI. Every change saves on its own and the schedule is generated again.

- **Workload and rest:** hours per day (the same setting as the plan), a **daily maximum**
  (up to 8 h, only used when a deadline would be missed otherwise), **rest kept each day**
  (free time inside your study window), the length of a focus block, the break between blocks,
  and a **buffer** of days before deadlines (work is planned to finish that many days early).
  **Study from / until** sets the window blocks go in.
- **Course weights:** a course with weight 2 gets about twice the time of one with weight 1;
  0 leaves it out. The slider shows the share you asked for and the share planned. Courses
  take turns (never the same course twice in a row when another has work), and work for a
  close deadline comes first.
- **When you can't study:** weekly slots (classes, work, training) and specific days or hours
  (appointments, travel, all-day off). Blocks never overlap them.
- **Activities:** *Deep work* blocks for sections (with their files), *Practice* blocks for
  assignments and quizzes, two short *Active recall* blocks one and four days after you finish
  a section (spaced repetition; untick **Spaced active recall** to drop them), and a short
  *Flashcards* block each day once you have flashcards.

**Download .ics** saves the blocks as a calendar file for Google Calendar (*Settings › Import*),
Apple Calendar (*File › Import*) or Outlook (*Add calendar › Upload from file*). Each event is
called like `[Study] LA: Matrices (Deep work)`, with what to do, the files (links into the app)
and the Moodle link in the description. Events keep the same ids per day and position, so
some apps update them when you import a newer schedule; others add copies, so delete the old
import first there. Times use the
server's `TIMEZONE`.

## Calendar and ICS export

The **Calendar** tab shows deadlines in month, week and list views (list by default on a
phone). Tap an item for details and *Mark done*.

To see deadlines in your phone or Outlook calendar, tap **Show subscription link**:

- **iPhone:** tap **Subscribe on this device** and confirm.
- **Google Calendar** (shows on Android): on a computer, *Settings → Add calendar → From URL*,
  paste the link.
- **Outlook:** *Add calendar → Subscribe from web*, paste the link.

Calendar apps refresh subscriptions on their own schedule (from every few minutes to about
a day). Each deadline has the alarms you chose under **Reminders** (by default one day and two
hours before); done items are prefixed ✓. The daily study reminders come in the same feed.

The link contains a private token, so anyone with it can read your deadline titles (nothing
else). If it leaks, tap **New link**: the old one stops working at once and you subscribe
again with the new one. The token is stripped from Caddy's and the app's logs.
**Download .ics** gives a one-off file instead, if you'd rather import than subscribe.

## Ask Claude (prompt builder)

Builds a ready-to-paste prompt for Claude (with the connector from
[connector.md](connector.md) turned on):

- **Course**: one or more. **Period**: last 2 months, last 4 weeks, until the next deadline,
  the whole course, your own dates, or a section range (one course only).
- **Goal**: catch-up summary, study plan, explain a topic, quiz me, flashcards, exam prep,
  understand an assignment, review saved questions, revision sheet (one page to remember),
  work on my weak spots (from the questions you missed), focused study session (the next item
  of your plan, step by step, then logs the time), or practice exercises (in the course's
  style, with hints). **Depth**, **time available** and the **language** of the answers
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
