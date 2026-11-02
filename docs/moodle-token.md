# Connecting your Moodle (token, SSO)

Study Companion reads Moodle the same way the official Moodle mobile app does: through the
`moodle_mobile_app` web service with a personal **token**. You don't register anything with
your university and you don't need an API key. If the Moodle app works with your site, this
works too.

Once you have a token, open **Settings** in Study Companion (`https://<your-domain>/settings`),
enter your Moodle address (for example `https://moodle.your-university.ch`), paste the token
and press **Test and save**. The app checks it against Moodle, stores it encrypted, and starts
the first sync. You never edit `.env` for this.

> The token gives full access to your Moodle account. Study Companion stores it encrypted
> with `SECRET_KEY`, never shows it again and never logs it. Don't paste it anywhere else.

## Option 1: the Security keys page (try this first)

1. Sign in to Moodle in a browser (your university login / SSO is fine).
2. Open your avatar menu > **Preferences** > **Security keys**
   (or go straight to `https://<moodle>/user/managetoken.php`).
3. Find the row for the service **Moodle mobile web service** and copy its **Key**.
4. Paste it into the Token field on the settings page.

No such row? Sign in once with the official **Moodle app** on your phone (it creates the
key), then reload the page. Some universities hide the Security keys page entirely; then use
option 2.

## Option 2: capture the token from the Moodle app sign-in (SSO fallback)

This uses the same sign-in page the Moodle app opens for SSO, but in your desktop browser.

1. In a desktop browser (Chrome, Edge or Firefox), sign in to Moodle normally.
2. Open the developer tools (**F12**) and select the **Console** tab.
3. In the same tab, open this address (replace the Moodle address with yours):

   ```
   https://moodle.your-university.ch/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=12345&urlscheme=moodlemobile
   ```

4. Complete the university sign-in if asked. Moodle then tries to open the Moodle app with a
   link that starts with `moodlemobile://token=`. Your browser can't open it, and shows it:
   - **Chrome / Edge:** the Console shows *Failed to launch 'moodlemobile://token=…'*. Copy the
     link between the quotes.
   - **Firefox:** a page says the address wasn't understood; copy the link from the address
     bar, or from the Console/Network tab.
5. Paste the whole `moodlemobile://token=…` link into the Token field. Study Companion
   decodes it and keeps only the token (the private part of the link is discarded).

Notes:
- The `passport` value can be any number.
- Moodle refuses this for site administrators, and a site can disable it (setting
  *Type of login* for the app). If it doesn't work, ask your Moodle support how to use the
  Moodle app with your account, then use option 1.
- The QR code shown on your Moodle profile for the app can't be used: it only works from the
  Moodle app itself, on the same network.

## No SSO? Username and password

If your site uses plain Moodle accounts, expand **No SSO?** on the settings page and enter
your Moodle username and password. They are used once to get a token from
`/login/token.php`; the password is not stored.

## When the token stops working

A token can expire or be revoked: your university may give tokens a validity period, and
pressing **Reset** on the Security keys page, changing your Moodle password or an admin
action can invalidate it. The sync then stops with *"The Moodle token is missing, invalid or
expired"* on the home page. Get a new token with option 1 or 2 and paste it on the settings
page; your synced courses and files stay as they are.

Changing `SECRET_KEY` also makes the stored token unreadable (it is encrypted with it); the
settings page then asks you to paste it again.

## Course languages

Each course records its language: the language forced on the course in Moodle (course `lang`
field) when there is one, otherwise a language detected from the course's names and
summaries (English, French, Spanish), otherwise your Moodle profile language. Course and
section names that use Moodle's multi-language markup are shown in that language. Later
milestones use it so summaries and prompts match each course.

## What is synced

Courses you are enrolled in, their sections and activities, files (resources, folders, pages),
activity completion, and deadlines from assignments, quizzes and calendar action events.
Files go to `/data/courses/<course>/<NN section>/` on the server and are only downloaded
again when Moodle reports a change. Files over `MOODLE_MAX_FILE_MB` (default 200 MB, usually
videos) are listed but not downloaded. The sync runs every `SYNC_INTERVAL_HOURS` (default 6)
and when you press **Sync now**; requests are limited to about 2 per second.
