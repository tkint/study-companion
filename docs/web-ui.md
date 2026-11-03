# Using the web UI

Open `https://<DOMAIN>` and sign in with your app password. The UI is built for phones first:
on a narrow screen the tabs (**Today**, **Courses**, **Calendar**, **Settings**) sit at the bottom.

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
- **Sync now** fetches from Moodle; the page refreshes when the sync ends.
- **Catch-up progress**: per course, the share of activities you completed, out of those
  Moodle tracks completion for (Moodle's own course progress when it reports one).

All times are shown in your device's time zone.

## Courses

Each course lists its open deadlines, then its sections with activities and files.

- **PDFs** open in the built-in viewer (pinch or −/+ to zoom, ⤓ to download).
- **Images and text files** open in a new tab; **everything else** (Word, PowerPoint, HTML…)
  downloads, so it opens in the right app on your phone. Course HTML is never rendered by
  the site itself, for safety.
- Files Moodle marks as too large (videos, over `MOODLE_MAX_FILE_MB`) aren't kept on the
  server: use the *open in Moodle* link.

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
