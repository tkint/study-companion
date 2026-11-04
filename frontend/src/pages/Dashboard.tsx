import { useEffect, useRef, useState } from "react";
import { api, type Dashboard as DashboardData, type Deadline, type Stats, type SyncState } from "../api";
import { Status, useLoad } from "../components/common";
import { CourseList } from "../components/CourseList";
import { DeadlineList } from "../components/DeadlineList";
import { Icon, type IconName } from "../components/Icon";
import { fromNow } from "../format";
import { href } from "../router";
import { minutes, PlanRow } from "./Plan";

// The home page leads with what you did (streak, this week's wins, progress) and the next few
// things to do. Past items sit folded away under "catch up", so the page never opens on a
// wall of red.

const UP_NEXT = 5;

function replace(list: Deadline[], d: Deadline) {
  return list.map((x) => (x.id === d.id ? d : x));
}

export default function Dashboard() {
  const { data, error, reload, setData } = useLoad(api.dashboard, []);

  function changed(d: Deadline) {
    if (!data) return;
    // Keep the item in place until the next load, so "Undo" stays under your thumb.
    setData({
      ...data,
      overdue: replace(data.overdue, d),
      this_week: replace(data.this_week, d),
      later: replace(data.later, d),
    });
  }

  if (!data) return <Status error={error} loading />;
  return (
    <>
      <SyncNotice sync={data.sync} onDone={reload} />
      <Hero data={data} />
      <Wins stats={data.stats} />

      <div className="dash">
        <div>
          <StudyToday data={data} onChange={reload} />
          <UpNext data={data} onChange={changed} />
          <CatchUpList items={data.overdue} onChange={changed} />
        </div>
        <section className="dash-side" id="progress">
          <h2><Icon name="book" /> Your courses</h2>
          <CourseList courses={data.courses} search={data.courses.length > 4} />
        </section>
      </div>
      <p className="footnote">
        Study Companion {data.version} · <a href="/status">sync details</a>
      </p>
    </>
  );
}

// ---------------------------------------------------------------- hero

function greeting(hour: number): { text: string; icon: IconName } {
  if (hour < 5) return { text: "Good night", icon: "moon" };
  if (hour < 12) return { text: "Good morning", icon: "sunrise" };
  if (hour < 18) return { text: "Good afternoon", icon: "sun" };
  return { text: "Good evening", icon: "moon" };
}

function cheer(stats: Stats): string {
  if (stats.studied_today && stats.streak > 1) return `${stats.streak} days in a row. You're on a roll!`;
  if (stats.studied_today) return "You already studied today. Nice work!";
  if (stats.streak > 0) return `Your ${stats.streak}-day streak is waiting. One small step keeps it going.`;
  if (stats.total.sections_studied + stats.total.deadlines_done + stats.total.cards_learned > 0)
    return "Welcome back! Pick one small thing to get going.";
  return "Every bit counts. Start with one small thing today.";
}

function overallProgress(data: DashboardData): { value: number; label: string } | null {
  const catchUp = data.catch_up;
  if (catchUp && catchUp.target_percent > 0) {
    return {
      value: Math.min(100, (100 * catchUp.percent) / catchUp.target_percent),
      label: catchUp.reached ? "target reached" : `of your ${catchUp.target_percent}% target`,
    };
  }
  const tracked = data.courses.filter((c) => c.progress != null);
  if (!tracked.length) return null;
  return {
    value: tracked.reduce((sum, c) => sum + (c.progress ?? 0), 0) / tracked.length,
    label: "course progress",
  };
}

function Hero({ data }: { data: DashboardData }) {
  const g = greeting(new Date().getHours());
  const progress = overallProgress(data);
  return (
    <section className="hero" aria-label="Welcome">
      <div className="hero-main">
        <h1><Icon name={g.icon} className="hero-icon" /> {g.text}!</h1>
        <p className="hero-cheer">{cheer(data.stats)}</p>
        <WeekStrip stats={data.stats} />
      </div>
      {progress && <Ring value={progress.value} label={progress.label} />}
    </section>
  );
}

function WeekStrip({ stats }: { stats: Stats }) {
  return (
    <ol className="week-strip" aria-label="Study days this week">
      {stats.week.map((d, i) => {
        const day = new Date(`${d.date}T12:00:00`);
        const today = i === stats.week.length - 1;
        const name = day.toLocaleDateString(undefined, { weekday: "long" });
        return (
          <li key={d.date} className={`${d.active ? "on" : ""}${today ? " today" : ""}`}
            title={`${name}: ${d.active ? "studied" : "no study"}`}>
            <span className="dot">{d.active && <Icon name="check" />}</span>
            <span className="day">{day.toLocaleDateString(undefined, { weekday: "narrow" })}</span>
            <span className="sr-only">{name}: {d.active ? "studied" : "no study"}</span>
          </li>
        );
      })}
    </ol>
  );
}

function Ring({ value, label }: { value: number; label: string }) {
  const r = 34;
  const c = 2 * Math.PI * r;
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const t = requestAnimationFrame(() => setShown(Math.max(0, Math.min(100, value))));
    return () => cancelAnimationFrame(t);
  }, [value]);
  const n = useCountUp(Math.round(value));
  return (
    <div className="ring" role="img" aria-label={`${Math.round(value)}% ${label}`}>
      <svg viewBox="0 0 80 80" aria-hidden="true">
        <circle cx="40" cy="40" r={r} className="ring-track" />
        <circle cx="40" cy="40" r={r} className="ring-fill" strokeDasharray={c}
          strokeDashoffset={c * (1 - shown / 100)} />
      </svg>
      <div className="ring-text" aria-hidden="true">
        <strong>{n}%</strong>
        <span>{label}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- wins

function useCountUp(target: number, ms = 700): number {
  const [n, setN] = useState(target);
  const from = useRef(0);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || target === 0) {
      setN(target);
      from.current = target;
      return;
    }
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      const eased = 1 - (1 - k) ** 3;
      setN(Math.round(a + (target - a) * eased));
      if (k < 1) raf = requestAnimationFrame(step);
      else from.current = target;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return n;
}

function Win({ icon, tone, value, suffix = "", label, sub }: {
  icon: IconName; tone: string; value: number; suffix?: string; label: string; sub?: string;
}) {
  const n = useCountUp(value);
  return (
    <li className={`win ${tone}`}>
      <span className="win-icon"><Icon name={icon} /></span>
      <strong>{n}{suffix}</strong>
      <span className="win-label">{label}</span>
      {sub && <span className="win-sub">{sub}</span>}
    </li>
  );
}

function Wins({ stats }: { stats: Stats }) {
  const w = stats.this_week;
  const done = w.deadlines_done + w.sections_studied;
  return (
    <ul className="wins" aria-label="Your stats">
      <Win icon="flame" tone="t-flame" value={stats.streak} label={stats.streak === 1 ? "day streak" : "days streak"}
        sub={stats.best_streak > stats.streak ? `best ${stats.best_streak}` : stats.streak > 1 ? "your best yet!" : undefined} />
      <Win icon="checkCircle" tone="t-ok" value={done} label="done this week"
        sub={`${w.sections_studied} section${w.sections_studied === 1 ? "" : "s"} · ${w.deadlines_done} task${w.deadlines_done === 1 ? "" : "s"}`} />
      <Win icon="cards" tone="t-sky" value={w.cards_reviewed} label="cards reviewed"
        sub={`${stats.total.cards_learned} learned in total`} />
      {w.quiz_percent != null ? (
        <Win icon="trophy" tone="t-sun" value={w.quiz_percent} suffix="%" label="quiz average"
          sub={`${w.quizzes} quiz${w.quizzes === 1 ? "" : "zes"} this week`} />
      ) : (
        <Win icon="note" tone="t-sun" value={stats.total.summaries} label={stats.total.summaries === 1 ? "summary" : "summaries"}
          sub="saved by Claude" />
      )}
    </ul>
  );
}

// ---------------------------------------------------------------- today and next

function StudyToday({ data, onChange }: { data: DashboardData; onChange: () => void }) {
  const plan = data.plan;
  const today = plan.today;
  const due = data.study.due;
  if (!today && !due && !plan.sections_left) return null;
  return (
    <section id="today" className="panel">
      <div className="list-head">
        <h2><Icon name="target" /> Today's plan{today ? ` · ${minutes(today.minutes)}` : ""}</h2>
        <a href={href.plan} className="small">Full plan <Icon name="arrow" /></a>
      </div>
      {due > 0 && (
        <div className="banner soft">
          <span><Icon name="cards" /> <strong>{due}</strong> flashcard{due === 1 ? "" : "s"} ready for review</span>
          <a className="btn small" href={href.study({ due: true })}>Let's go</a>
        </div>
      )}
      {today ? (
        <ul className="plan-list">
          {today.items.map((it, i) => <PlanRow key={i} item={it} onStudied={onChange} />)}
        </ul>
      ) : (
        <p className="empty happy"><Icon name="leaf" /> Nothing planned today. Enjoy it!</p>
      )}
      {plan.late > 0 && (
        <p className="hint small">
          {plan.late} item{plan.late === 1 ? "" : "s"} this week won't fit before {plan.late === 1 ? "its" : "their"} deadline
          at {plan.hours_per_day} h a day. You can adjust that in the <a href={href.plan}>plan</a>.
        </p>
      )}
    </section>
  );
}

function UpNext({ data, onChange }: { data: DashboardData; onChange: (d: Deadline) => void }) {
  const [all, setAll] = useState(false);
  const items = [...data.this_week, ...data.later];
  const shown = all ? items : data.this_week.slice(0, UP_NEXT);
  const more = items.length - shown.length;
  return (
    <section id="next">
      <div className="list-head">
        <h2><Icon name="calendar" /> Coming up</h2>
        <a href={href.calendar} className="small">Calendar <Icon name="arrow" /></a>
      </div>
      <DeadlineList items={shown}
        empty={data.later.length ? "Nothing due in the next 7 days. Enjoy the breathing room." : "Nothing scheduled. Enjoy the breathing room."}
        onChange={onChange} />
      {more > 0 && (
        <button className="btn ghost small more" onClick={() => setAll(true)}>
          Show {more} more
        </button>
      )}
    </section>
  );
}

function CatchUpList({ items, onChange }: { items: Deadline[]; onChange: (d: Deadline) => void }) {
  const open = items.filter((d) => !d.done).length;
  if (!items.length) {
    return (
      <p className="all-caught-up"><Icon name="sparkles" /> You're all caught up on past work.</p>
    );
  }
  return (
    <details className="catchup" id="catch-up">
      <summary>
        <Icon name="leaf" />
        <span>
          <strong>{open ? `${open} past item${open === 1 ? "" : "s"} to catch up on` : "Past items all handled"}</strong>
          <span className="muted small">No rush: pick what matters to you and go at your own pace.</span>
        </span>
      </summary>
      <DeadlineList items={items} empty="" onChange={onChange} />
    </details>
  );
}

// ---------------------------------------------------------------- sync

function SyncNotice({ sync: initial, onDone }: { sync: SyncState; onDone: () => void }) {
  const [sync, setSync] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setSync(initial), [initial]);

  useEffect(() => {
    if (!sync.running) return;
    const t = window.setInterval(async () => {
      try {
        const s = await api.sync();
        setSync(s);
        if (!s.running) onDone();
      } catch {
        /* keep polling */
      }
    }, 3000);
    return () => window.clearInterval(t);
  }, [sync.running, onDone]);

  async function start() {
    setError(null);
    try {
      await api.startSync();
      setSync({ ...sync, running: true });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!sync.configured) {
    return (
      <p className="banner warn">
        Moodle is not connected yet. <a href="/settings">Open Settings</a> to add your Moodle address and token.
      </p>
    );
  }
  const run = sync.last_run;
  const failed = run && run.status !== "ok" && !sync.running;
  return (
    <div className={`sync-pill${failed ? " warn" : ""}`}>
      <span>
        <Icon name="refresh" className={sync.running ? "spin" : undefined} />
        {sync.running
          ? "Syncing with Moodle…"
          : run
            ? `Synced ${fromNow(run.finished_at ?? run.started_at)}${run.status === "ok" ? "" : ` (${run.status})`}`
            : "Not synced yet"}
        {error && <span className="late"> · {error}</span>}
      </span>
      <button className="link" onClick={start} disabled={sync.running}>
        {sync.running ? "" : "Sync now"}
      </button>
    </div>
  );
}
