import { useEffect, useState } from "react";
import { api, type TimeSummary } from "../api";
import { Progress, Status, useLoad } from "../components/common";
import { courseColor, minutesLabel, when } from "../format";
import { href } from "../router";

// Study time: a timer you start and stop (it survives reloads and closing the app), manual
// entries, and the totals: today against the daily goal, this week, the streak.
// Claude logs its sessions too (MCP tool log_study_time). Backend: app/study_time.py.

const TIMER_KEY = "study-timer";
const MAX_MINUTES = 12 * 60;

interface Timer {
  start: number; // ms
  course: number | null;
}

function loadTimer(): Timer | null {
  try {
    const raw = localStorage.getItem(TIMER_KEY);
    const t = raw ? JSON.parse(raw) : null;
    return t && typeof t.start === "number" ? { start: t.start, course: t.course ?? null } : null;
  } catch {
    return null;
  }
}

function saveTimer(t: Timer | null) {
  try {
    if (t) localStorage.setItem(TIMER_KEY, JSON.stringify(t));
    else localStorage.removeItem(TIMER_KEY);
  } catch {
    /* private mode: the timer just won't survive a reload */
  }
}

function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

const weekday = new Intl.DateTimeFormat(navigator.language || "en", { weekday: "narrow" });
const longDay = new Intl.DateTimeFormat(navigator.language || "en", { weekday: "long", day: "numeric", month: "short" });
const day = (iso: string) => new Date(`${iso}T12:00:00`);

function encouragement(s: TimeSummary): string {
  const goal = s.goal_minutes_per_day;
  if (goal && s.today_minutes >= goal) return "Daily goal reached. Well done! 🎉";
  if (s.today_minutes > 0) return "Nice start today. Every minute counts.";
  if (s.streak_days > 0) return `Keep your ${s.streak_days}-day streak going with a short session today.`;
  return "A short session is a great way to start. Try 25 minutes.";
}

export default function Time() {
  const { data, error, setData } = useLoad(() => api.studyTime(), []);
  const courses = useLoad(() => api.dashboard().then((d) => d.courses), []);
  const [timer, setTimer] = useState<Timer | null>(loadTimer);
  const [now, setNow] = useState(Date.now());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [manual, setManual] = useState({ minutes: "30", course: "", note: "" });

  useEffect(() => {
    if (!timer) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [timer]);

  if (!data) return <Status error={error} loading />;
  const goal = data.goal_minutes_per_day;
  const max = Math.max(goal * 1.15, ...data.days.map((d) => d.minutes), 1);
  const courseList = courses.data ?? [];

  const save = async (e: Parameters<typeof api.logTime>[0]) => {
    setBusy(true);
    setMessage(null);
    try {
      const before = data.today_minutes;
      const r = await api.logTime(e);
      setData(r.summary);
      const reached = goal > 0 && before < goal && r.summary.today_minutes >= goal;
      setMessage(reached ? "Daily goal reached! 🎉" : `Saved ${minutesLabel(r.entry.minutes)}.`);
      return true;
    } catch (err) {
      setMessage((err as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const start = () => {
    const t = { start: Date.now(), course: manual.course ? Number(manual.course) : null };
    saveTimer(t);
    setTimer(t);
    setNow(Date.now());
    setMessage(null);
  };

  const stop = async () => {
    if (!timer) return;
    const minutes = Math.min(MAX_MINUTES, Math.round((Date.now() - timer.start) / 60000));
    if (minutes < 1) {
      saveTimer(null);
      setTimer(null);
      setMessage("Less than a minute: not saved.");
      return;
    }
    if (await save({ minutes, course_id: timer.course, started_at: Math.floor(timer.start / 1000), source: "timer" })) {
      saveTimer(null);
      setTimer(null);
    }
  };

  const cancel = () => {
    saveTimer(null);
    setTimer(null);
  };

  const addManual = async (ev: React.FormEvent) => {
    ev.preventDefault();
    const minutes = Number(manual.minutes);
    if (!Number.isFinite(minutes) || minutes < 1) return setMessage("Enter the minutes you studied.");
    await save({ minutes: Math.round(minutes), course_id: manual.course ? Number(manual.course) : null,
      note: manual.note.trim(), source: "manual" });
  };

  const remove = async (id: number) => {
    await api.deleteTime(id);
    setData(await api.studyTime());
  };

  const timerCourse = timer?.course != null ? courseList.find((c) => c.id === timer.course) : undefined;

  return (
    <>
      <h1>Study time</h1>
      <p className="muted">{encouragement(data)}</p>

      <div className="summary time-stats">
        <div className="stat static">
          <strong>{minutesLabel(data.today_minutes)}</strong>
          <span>today{goal ? ` · goal ${minutesLabel(goal)}` : ""}</span>
        </div>
        <div className="stat static">
          <strong>{minutesLabel(data.week_minutes)}</strong>
          <span>this week</span>
        </div>
        <div className="stat static">
          <strong>{data.streak_days} {data.streak_days > 0 ? "🔥" : ""}</strong>
          <span>day{data.streak_days === 1 ? "" : "s"} in a row</span>
        </div>
      </div>
      {goal > 0 && <Progress value={(100 * data.today_minutes) / goal} />}

      <section className="field time-timer" aria-live="polite">
        {timer ? (
          <>
            <div className="time-clock">{clock(now - timer.start)}</div>
            <p className="muted">{timerCourse ? timerCourse.fullname : "General study"} · started {when(Math.floor(timer.start / 1000))}</p>
            <div className="row">
              <button className="btn" onClick={stop} disabled={busy}>Stop and save</button>
              <button className="btn ghost" onClick={cancel} disabled={busy}>Discard</button>
            </div>
          </>
        ) : (
          <>
            <label className="block">
              <span>Course</span>
              <select className="full" value={manual.course} onChange={(e) => setManual({ ...manual, course: e.target.value })}>
                <option value="">General study</option>
                {courseList.map((c) => <option key={c.id} value={c.id}>{c.fullname}</option>)}
              </select>
            </label>
            <div className="row">
              <button className="btn wide" onClick={start}>▶ Start the timer</button>
            </div>
            <p className="muted small-print">The timer keeps running if you close the app.</p>
          </>
        )}
        {message && <p className="time-message">{message}</p>}
      </section>

      <h2>Last 14 days</h2>
      <div className="time-chart" role="img"
        aria-label={`Minutes per day: ${data.days.map((d) => `${d.date} ${d.minutes}`).join(", ")}`}>
        <div className="time-plot">
        {goal > 0 && <div className="time-goal" style={{ bottom: `${(100 * goal) / max}%` }} title={`Goal ${minutesLabel(goal)}`} />}
        {data.days.map((d) => (
          <div key={d.date} className="time-bar" title={`${longDay.format(day(d.date))}: ${minutesLabel(d.minutes)}`}>
            <span className={goal && d.minutes >= goal ? "met" : ""} style={{ height: `${(100 * d.minutes) / max}%` }} />
            <small className={d.date === data.today ? "today" : ""}>{weekday.format(day(d.date))}</small>
          </div>
        ))}
        </div>
      </div>
      <p className="muted time-facts">
        {data.best_day ? <>Best day: {minutesLabel(data.best_day.minutes)} on {longDay.format(day(data.best_day.date))}. </> : null}
        {data.total_minutes > 0 && <>Total so far: {minutesLabel(data.total_minutes)}.</>}
        {" "}Daily goal comes from the <a href={href.plan}>catch-up plan</a>'s hours per day.
      </p>

      {data.courses.length > 0 && (
        <>
          <h2>Last 7 days by course</h2>
          <ul className="time-courses">
            {data.courses.map((c) => (
              <li key={c.course_id ?? 0}>
                <span className="time-dot" style={{ background: courseColor(c.course_id) }} />
                <span className="grow">{c.course_name || "General study"}</span>
                <strong>{minutesLabel(c.minutes)}</strong>
              </li>
            ))}
          </ul>
        </>
      )}

      <h2>Add time by hand</h2>
      <form className="field" onSubmit={addManual}>
        <div className="time-form">
          <label className="block">
            <span>Minutes</span>
            <input type="number" min={1} max={MAX_MINUTES} inputMode="numeric" value={manual.minutes}
              onChange={(e) => setManual({ ...manual, minutes: e.target.value })} />
          </label>
          <label className="block">
            <span>Course</span>
            <select value={manual.course} onChange={(e) => setManual({ ...manual, course: e.target.value })}>
              <option value="">General study</option>
              {courseList.map((c) => <option key={c.id} value={c.id}>{c.fullname}</option>)}
            </select>
          </label>
        </div>
        <label className="block">
          <span>Note (optional)</span>
          <input type="text" className="full" maxLength={200} value={manual.note}
            onChange={(e) => setManual({ ...manual, note: e.target.value })} placeholder="e.g. read chapter 3" />
        </label>
        <div className="row">
          <button className="btn" type="submit" disabled={busy}>Add</button>
        </div>
      </form>

      {data.recent.length > 0 && (
        <>
          <h2>Recent sessions</h2>
          <ul className="time-courses">
            {data.recent.slice(0, 8).map((e) => (
              <li key={e.id}>
                <span className="time-dot" style={{ background: courseColor(e.course_id) }} />
                <span className="grow">
                  {e.course_shortname || e.course_name || "General study"}
                  {e.note && <span className="muted"> · {e.note}</span>}
                  <br />
                  <small className="muted">
                    {when(e.started_at)} · {e.source === "claude" ? "logged by Claude" : e.source === "timer" ? "timer" : "added by hand"}
                  </small>
                </span>
                <strong>{minutesLabel(e.minutes)}</strong>
                <button className="btn small ghost" onClick={() => remove(e.id)} aria-label="Delete this session">✕</button>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
