import { useEffect, useState, type ReactElement } from "react";
import { api, type ReminderPrefs, type Reminders as R } from "../api";
import { fromNow, minutesLabel } from "../format";
import { href } from "../router";

// In-app reminders: a friendly "today" card (cards to review, deadlines in the next 48 h,
// study time against the goal). The same reminders reach the phone through the calendar
// feed's alarms (app/reminders.py). Renders nothing when there is nothing to say.

export function Reminders() {
  const [data, setData] = useState<R | null>(null);
  useEffect(() => {
    api.reminders().then(setData).catch(() => setData(null));
  }, []);
  if (!data) return null;
  const goalMet = data.goal_minutes > 0 && data.studied_minutes >= data.goal_minutes;
  const lines: ReactElement[] = [];
  if (data.cards_due > 0) {
    lines.push(
      <li key="cards">
        <span aria-hidden="true">🧠</span>
        <span><a href={href.study({ due: true })}>{data.cards_due} card{data.cards_due === 1 ? "" : "s"} to review</a> · a few minutes is enough</span>
      </li>,
    );
  }
  for (const d of data.deadlines_soon) {
    lines.push(
      <li key={`d${d.id}`}>
        <span aria-hidden="true">📌</span>
        <span>{d.course_shortname ? `${d.course_shortname}: ` : ""}{d.name} · due {fromNow(d.due_at, data.now)}</span>
      </li>,
    );
  }
  if (goalMet) {
    lines.push(
      <li key="goal">
        <span aria-hidden="true">🎉</span>
        <span>Daily goal reached: {minutesLabel(data.studied_minutes)} today</span>
      </li>,
    );
  } else if (data.planned_minutes > 0 || data.studied_minutes > 0) {
    lines.push(
      <li key="time">
        <span aria-hidden="true">⏱</span>
        <span>
          {data.studied_minutes > 0 ? `${minutesLabel(data.studied_minutes)} studied today` : "Nothing logged yet today"}
          {data.planned_minutes > 0 && <> · <a href={href.plan}>{minutesLabel(data.planned_minutes)} planned</a></>}
          {" "}· <a href={href.time}>timer</a>
        </span>
      </li>,
    );
  }
  if (!lines.length) return null;
  return (
    <section className="reminders" aria-label="Reminders for today">
      <ul>{lines}</ul>
    </section>
  );
}

const ALARM_CHOICES = [
  { minutes: 10080, label: "1 week" },
  { minutes: 2880, label: "2 days" },
  { minutes: 1440, label: "1 day" },
  { minutes: 120, label: "2 hours" },
  { minutes: 60, label: "1 hour" },
];

export function ReminderSettings() {
  const [prefs, setPrefs] = useState<ReminderPrefs | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  useEffect(() => {
    api.reminders().then((r) => setPrefs(r.prefs)).catch(() => setPrefs(null));
  }, []);
  if (!prefs) return null;

  const update = async (p: Partial<ReminderPrefs>) => {
    try {
      setPrefs(await api.setReminders(p));
      setSaved("Saved. Your calendar app picks it up at its next refresh.");
    } catch (e) {
      setSaved((e as Error).message);
    }
  };
  const toggle = (m: number) => {
    const has = prefs.deadline_alarms.includes(m);
    const next = has ? prefs.deadline_alarms.filter((x) => x !== m) : [...prefs.deadline_alarms, m];
    if (next.length > 3) return setSaved("Pick up to 3 alarms.");
    update({ deadline_alarms: next });
  };

  return (
    <section className="subscribe">
      <h2>Reminders</h2>
      <p className="muted">
        Reminders come as alarms in the calendar you subscribe to below, so your phone notifies
        you like any other event.
      </p>
      <fieldset className="field">
        <legend>Before each deadline</legend>
        <div className="chips">
          {ALARM_CHOICES.map((c) => (
            <label key={c.minutes} className="chip">
              <input type="checkbox" checked={prefs.deadline_alarms.includes(c.minutes)} onChange={() => toggle(c.minutes)} />
              <span>{c.label}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="field">
        <legend>Daily study reminder</legend>
        <label className="chip">
          <input type="checkbox" checked={prefs.daily_enabled} onChange={(e) => update({ daily_enabled: e.target.checked })} />
          <span>Remind me to study, with the day's plan and cards to review</span>
        </label>
        {prefs.daily_enabled && (
          <label className="block">
            <span>At</span>
            <input type="time" value={prefs.daily_time} step={300}
              onChange={(e) => /^\d\d:\d\d$/.test(e.target.value) && update({ daily_time: e.target.value })} />
          </label>
        )}
      </fieldset>
      {saved && <p className="muted small" role="status">{saved}</p>}
    </section>
  );
}
