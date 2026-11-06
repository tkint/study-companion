import { useEffect, useRef, useState } from "react";
import {
  api, type DatedUnavailability, type Schedule as ScheduleData, type ScheduleBlock, type ScheduleConfig,
  type WeeklyUnavailability,
} from "../api";
import { Status, useLoad } from "../components/common";
import { courseColor } from "../format";
import { href } from "../router";
import { minutes, PlanRow } from "./Plan";

// The timed study schedule (app/planner/schedule.py): the catch-up plan's work as focus blocks
// with times, around your weekly and dated unavailabilities, within your hours per day, rest
// hours and daily maximum. Changes save on their own and the schedule is generated again.
// "Download .ics" exports the blocks for Google Calendar, Apple Calendar or Outlook.

const WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const SAVE_DELAY = 600;

const KIND_TAG: Record<ScheduleBlock["kind"], string> = {
  deep: "",
  practice: "warn",
  recall: "ai",
  flashcards: "ok",
};

function hours(h: number): string {
  return minutes(Math.round(h * 60));
}

function clock(ts: number, timeZone?: string): string {
  const opts: Intl.DateTimeFormatOptions = { hour: "2-digit", minute: "2-digit" };
  try {
    return new Date(ts * 1000).toLocaleTimeString(undefined, { ...opts, timeZone });
  } catch {
    return new Date(ts * 1000).toLocaleTimeString(undefined, opts);
  }
}

function dayLabel(iso: string, today: string): string {
  if (iso === today) return "Today";
  const d = new Date(`${iso}T12:00:00`);
  const t = new Date(`${today}T12:00:00`);
  if (Math.round((d.getTime() - t.getTime()) / 86400000) === 1) return "Tomorrow";
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
}

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function Slider({ label, value, min, max, step, format, onChange, hint }: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
  hint?: string;
}) {
  return (
    <label className="sched-slider">
      <span className="sched-slider-head">
        <span>{label}</span>
        <strong>{format(value)}</strong>
      </span>
      <input type="range" className="range range-sm range-primary" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} />
      {hint && <span className="muted small">{hint}</span>}
    </label>
  );
}

export default function Schedule() {
  const { data, error, reload } = useLoad(() => api.schedule(), []);
  const [draft, setDraft] = useState<ScheduleConfig | null>(null);
  const [saveState, setSaveState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (data && !draft) setDraft(data.config);
  }, [data, draft]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  if (!data || !draft) return <Status error={error} loading />;
  const cfg = draft;

  function change(patch: Partial<ScheduleConfig>) {
    const next = { ...cfg, ...patch };
    if (next.daily_hours > next.max_daily_hours) next.daily_hours = next.max_daily_hours;
    setDraft(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      setSaveState({ busy: true, error: null });
      try {
        await api.setSchedule(next);
        setSaveState({ busy: false, error: null });
        reload();
      } catch (e) {
        setSaveState({ busy: false, error: (e as Error).message });
      }
    }, SAVE_DELAY);
  }

  return (
    <>
      <p className="crumbs"><a href={href.plan}>← Catch-up plan</a></p>
      <h1>Study schedule</h1>
      <p className="muted small">
        Your catch-up plan with times: focus blocks around your classes and commitments, short breaks in between,
        active recall a day and a few days after each section, and a margin before every deadline. Change anything
        below and the schedule updates.
      </p>
      <div className="sched-actions">
        <a className="btn btn-primary btn-sm" href="/api/schedule.ics" download>Download .ics</a>
        <span className="muted small" role="status">
          {saveState.busy ? "Saving…" : saveState.error ? <span className="late">{saveState.error}</span> : "Saved"}
        </span>
      </div>

      <Summary data={data} />
      {data.notes.map((n, i) => <p key={i} className="banner warn small">{n}</p>)}

      <details className="sched-panel" open>
        <summary>Workload and rest</summary>
        <div className="sched-grid">
          <Slider label="Hours per day" value={cfg.daily_hours} min={0.5} max={cfg.max_daily_hours} step={0.25}
            format={hours} onChange={(v) => change({ daily_hours: v })} hint="Your usual study time, shared with the plan." />
          <Slider label="Daily maximum" value={cfg.max_daily_hours} min={1} max={8} step={0.5} format={hours}
            onChange={(v) => change({ max_daily_hours: v })} hint="Only reached when a deadline needs it." />
          <Slider label="Rest kept each day" value={cfg.rest_hours} min={0} max={8} step={0.5} format={hours}
            onChange={(v) => change({ rest_hours: v })} hint="Free time inside your study window." />
          <Slider label="Focus block" value={cfg.session_minutes} min={20} max={120} step={5} format={minutes}
            onChange={(v) => change({ session_minutes: v })} />
          <Slider label="Break between blocks" value={cfg.break_minutes} min={0} max={30} step={5}
            format={(v) => (v ? minutes(v) : "none")} onChange={(v) => change({ break_minutes: v })} />
          <Slider label="Buffer before deadlines" value={cfg.buffer_days} min={0} max={7} step={1}
            format={(v) => (v ? `${v} day${v === 1 ? "" : "s"}` : "none")} onChange={(v) => change({ buffer_days: v })} />
        </div>
        <div className="sched-row">
          <label>Study from
            <input type="time" className="input input-sm" step={900} value={cfg.day_start}
              onChange={(e) => /^\d\d:\d\d$/.test(e.target.value) && change({ day_start: e.target.value })} />
          </label>
          <label>until
            <input type="time" className="input input-sm" step={900} value={cfg.day_end === "24:00" ? "23:59" : cfg.day_end}
              onChange={(e) => /^\d\d:\d\d$/.test(e.target.value) && change({ day_end: e.target.value === "23:59" ? "24:00" : e.target.value })} />
          </label>
          <label>Plan ahead
            <select className="select select-sm" value={cfg.days} onChange={(e) => change({ days: Number(e.target.value) })}>
              {[7, 14, 21, 30, 45, 60].concat([7, 14, 21, 30, 45, 60].includes(cfg.days) ? [] : [cfg.days])
                .sort((a, b) => a - b).map((v) => <option key={v} value={v}>{v} days</option>)}
            </select>
          </label>
        </div>
        <div className="view-toggles">
          <label><input type="checkbox" checked={cfg.recall} onChange={(e) => change({ recall: e.target.checked })} />
            Spaced active recall</label>
          <label><input type="checkbox" checked={cfg.include_optional} onChange={(e) => change({ include_optional: e.target.checked })} />
            Include optional work</label>
          <label><input type="checkbox" checked={cfg.beyond_target} onChange={(e) => change({ beyond_target: e.target.checked })} />
            Plan beyond my goal</label>
        </div>
      </details>

      <details className="sched-panel" open={data.courses.length > 1}>
        <summary>Course weights</summary>
        <p className="muted small">A course with weight 2 gets about twice the time of one with weight 1. 0 leaves it out.
          Deadlines can still come first.</p>
        <div className="sched-grid">
          {data.courses.map((c) => {
            const w = cfg.course_weights[String(c.id)] ?? 1;
            return (
              <div key={c.id} className="sched-course">
                <span className="swatch" style={{ background: courseColor(c.id) }} aria-hidden="true" />
                <Slider label={c.shortname || c.fullname} value={w} min={0} max={3} step={0.25}
                  format={(v) => (v ? `×${v}` : "off")}
                  onChange={(v) => change({ course_weights: { ...cfg.course_weights, [String(c.id)]: v } })}
                  hint={`${Math.round(c.target_share)}% of the time, ${Math.round(c.planned_share)}% planned (${minutes(c.planned_minutes)})`} />
              </div>
            );
          })}
        </div>
      </details>

      <details className="sched-panel" open={!cfg.weekly.length && !cfg.dates.length}>
        <summary>When you can't study ({cfg.weekly.length + cfg.dates.length})</summary>
        <WeeklyEditor rows={cfg.weekly} onChange={(weekly) => change({ weekly })} />
        <DatedEditor rows={cfg.dates} today={data.today} onChange={(dates) => change({ dates })} />
      </details>

      {!data.days.length && !data.unscheduled.length && <p className="empty">Nothing to schedule. 🎉</p>}
      {data.days.map((d) => (
        <section key={d.date}>
          <h2 className="day-head">
            <span>{dayLabel(d.date, data.today)}</span>
            <span className="muted small">
              {minutes(d.minutes)}{d.stretched && <span className="tag warn"> extra</span>}
            </span>
          </h2>
          {d.blocked.length > 0 && (
            <p className="small muted sched-blocked">
              {d.blocked.map((b, i) => (
                <span key={i} className="tag muted-tag">
                  {b.start === "00:00" && b.end === "24:00" ? "all day" : `${b.start}–${b.end}`}
                  {b.reason ? ` · ${b.reason}` : ""}
                </span>
              ))}
            </p>
          )}
          {d.blocks.length ? (
            <ul className="plan-list">{d.blocks.map((b, i) => <BlockRow key={i} block={b} timeZone={data.timezone} />)}</ul>
          ) : (
            <p className="muted small">No study blocks.</p>
          )}
        </section>
      ))}
      {data.unscheduled.length > 0 && (
        <section>
          <h2 className="day-head">
            <span>Doesn't fit in {cfg.days} days</span>
            <span className="muted small">{minutes(data.unscheduled_minutes)}</span>
          </h2>
          <ul className="plan-list">
            {data.unscheduled.map((it, i) => <PlanRow key={i} item={it} />)}
          </ul>
        </section>
      )}
    </>
  );
}

function Summary({ data }: { data: ScheduleData }) {
  const k = data.minutes_by_kind;
  return (
    <section className="summary" aria-label="Schedule summary">
      <div className="stat static"><strong>{minutes(data.total_minutes)}</strong><span>planned</span></div>
      <div className="stat static"><strong>{minutes((k.deep ?? 0) + (k.practice ?? 0))}</strong><span>reading and practice</span></div>
      <div className="stat static"><strong>{minutes((k.recall ?? 0) + (k.flashcards ?? 0))}</strong><span>recall and cards</span></div>
      <div className={`stat static${data.late ? " bad" : ""}`}>
        <strong>{data.late}</strong><span>late</span>
      </div>
    </section>
  );
}

function BlockRow({ block: b, timeZone }: { block: ScheduleBlock; timeZone?: string }) {
  const link = b.course_id ? href.course(b.course_id, b.section_id ?? undefined)
    : b.kind === "flashcards" ? href.study({ due: true }) : undefined;
  return (
    <li className={`plan-item${b.late ? " late-item" : ""}`}>
      <span className="swatch" style={{ background: b.course_id ? courseColor(b.course_id) : "var(--accent)" }} aria-hidden="true" />
      <div className="plan-main">
        <div className="small muted sched-time">{clock(b.start, timeZone)}–{clock(b.end, timeZone)}</div>
        <div className="plan-title">
          {link ? <a href={link}>{b.title}</a> : b.title}
          {b.parts > 1 && <span className="muted"> · {b.kind === "recall" ? "review" : "part"} {b.part}/{b.parts}</span>}
        </div>
        <div className="deadline-meta">
          {(b.course_short || b.course_name) && <span className="course-link">{b.course_short || b.course_name}</span>}
          <span className={`tag ${KIND_TAG[b.kind]}`}>{b.label}</span>
          {b.late && <span className="tag warn">late</span>}
        </div>
        {b.detail && <p className="small muted sched-detail">{b.detail}</p>}
        {b.files.length > 0 && (
          <p className="small sched-files">
            {b.files.map((f) => (
              <a key={f.id} href={href.file(f.id, b.course_id ?? undefined)}>{f.name}{f.pages ? ` (${f.pages} p.)` : ""}</a>
            ))}
          </p>
        )}
      </div>
      <div className="plan-side"><strong>{minutes(b.minutes)}</strong></div>
    </li>
  );
}

function WeeklyEditor({ rows, onChange }: { rows: WeeklyUnavailability[]; onChange: (r: WeeklyUnavailability[]) => void }) {
  const set = (i: number, patch: Partial<WeeklyUnavailability>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <fieldset className="sched-editor">
      <legend>Every week</legend>
      <p className="muted small">Classes, work shifts, training…</p>
      {rows.map((r, i) => (
        <div key={i} className="sched-slot">
          <select className="select select-sm" aria-label="Day" value={r.day} onChange={(e) => set(i, { day: Number(e.target.value) })}>
            {WEEKDAYS_SHORT.map((d, n) => <option key={n} value={n}>{d}</option>)}
          </select>
          <TimeRange start={r.start} end={r.end} onChange={(start, end) => set(i, { start, end })} />
          <input type="text" className="input input-sm" aria-label="Reason" placeholder="Reason" maxLength={80}
            value={r.reason} onChange={(e) => set(i, { reason: e.target.value })} />
          <button type="button" className="btn btn-sm btn-ghost" aria-label="Remove" onClick={() => onChange(rows.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <button type="button" className="btn btn-sm" disabled={rows.length >= 50}
        onClick={() => onChange([...rows, { day: 0, start: "09:00", end: "12:00", reason: "" }])}>+ Weekly slot</button>
    </fieldset>
  );
}

function DatedEditor({ rows, today, onChange }: {
  rows: DatedUnavailability[];
  today: string;
  onChange: (r: DatedUnavailability[]) => void;
}) {
  const set = (i: number, patch: Partial<DatedUnavailability>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const tomorrow = isoDate(new Date(new Date(`${today}T12:00:00`).getTime() + 86400000));
  const sorted = rows.map((r, i) => ({ r, i })).sort((a, b) => a.r.date.localeCompare(b.r.date));
  return (
    <fieldset className="sched-editor">
      <legend>On specific days</legend>
      <p className="muted small">Appointments, travel, days off…</p>
      {sorted.map(({ r, i }) => {
        const allDay = r.start === "00:00" && r.end === "24:00";
        return (
          <div key={i} className={`sched-slot${r.date < today ? " sched-past" : ""}`}>
            <input type="date" className="input input-sm" aria-label="Date" value={r.date}
              onChange={(e) => e.target.value && set(i, { date: e.target.value })} />
            <label className="sched-allday">
              <input type="checkbox" checked={allDay}
                onChange={(e) => set(i, e.target.checked ? { start: "00:00", end: "24:00" } : { start: "09:00", end: "12:00" })} />
              all day
            </label>
            {!allDay && <TimeRange start={r.start} end={r.end} onChange={(start, end) => set(i, { start, end })} />}
            <input type="text" className="input input-sm" aria-label="Reason" placeholder="Reason" maxLength={80}
              value={r.reason} onChange={(e) => set(i, { reason: e.target.value })} />
            <button type="button" className="btn btn-sm btn-ghost" aria-label="Remove" onClick={() => onChange(rows.filter((_, j) => j !== i))}>✕</button>
          </div>
        );
      })}
      <button type="button" className="btn btn-sm" disabled={rows.length >= 100}
        onClick={() => onChange([...rows, { date: tomorrow, start: "00:00", end: "24:00", reason: "" }])}>+ Day off or appointment</button>
    </fieldset>
  );
}

function TimeRange({ start, end, onChange }: { start: string; end: string; onChange: (start: string, end: string) => void }) {
  const ok = (v: string) => /^\d\d:\d\d$/.test(v);
  return (
    <span className="sched-range">
      <input type="time" className="input input-sm" aria-label="From" step={900} value={start}
        onChange={(e) => ok(e.target.value) && onChange(e.target.value, end)} />
      <span aria-hidden="true">–</span>
      <input type="time" className="input input-sm" aria-label="Until" step={900} value={end === "24:00" ? "23:59" : end}
        onChange={(e) => ok(e.target.value) && onChange(start, e.target.value === "23:59" ? "24:00" : e.target.value)} />
    </span>
  );
}
