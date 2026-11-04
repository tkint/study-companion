import { useState } from "react";
import { api, type Plan as PlanData, type PlanItem, type PlanSlot } from "../api";
import { Status, useLoad } from "../components/common";
import { celebrate } from "../components/Confetti";
import { Icon } from "../components/Icon";
import { courseColor, sourceLabel, when } from "../format";
import { href } from "../router";

// The rule-based catch-up plan (app/planner): sections left to study and open deadlines,
// ordered by urgency and spread over the days at your hours per day.

export function minutes(m: number): string {
  const h = Math.floor(m / 60);
  const r = m % 60;
  if (!h) return `${r} min`;
  return r ? `${h} h ${String(r).padStart(2, "0")}` : `${h} h`;
}

function dayLabel(iso: string, today: string): string {
  if (iso === today) return "Today";
  const d = new Date(`${iso}T12:00:00`);
  const t = new Date(`${today}T12:00:00`);
  if ((d.getTime() - t.getTime()) / 86400000 === 1) return "Tomorrow";
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
}

export function PlanRow({ item, onStudied }: { item: PlanSlot | PlanItem; onStudied?: (sectionId: number) => void }) {
  const slot = "minutes_today" in item ? item : null;
  const [busy, setBusy] = useState(false);
  const isSection = item.kind === "section";
  async function studied(e: React.MouseEvent<HTMLButtonElement>) {
    if (!item.section_id) return;
    const button = e.currentTarget;
    setBusy(true);
    try {
      await api.setStudied(item.section_id, true);
      celebrate(button, 60);
      onStudied?.(item.section_id);
    } finally {
      setBusy(false);
    }
  }
  const link = isSection && item.course_id
    ? href.course(item.course_id, item.section_id ?? undefined)
    : item.course_id ? href.course(item.course_id) : undefined;
  return (
    <li className={`plan-item${slot?.late ? " late-item" : ""}${item.overdue ? " overdue" : ""}`}>
      <span className="swatch" style={{ background: courseColor(item.course_id) }} aria-hidden="true" />
      <div className="plan-main">
        <div className="plan-title">
          {link ? <a href={link}>{item.title}</a> : item.title}
          {slot && slot.parts > 1 && <span className="muted"> · part {slot.part}/{slot.parts}</span>}
        </div>
        <div className="deadline-meta">
          <span className="course-link">{item.course_short || item.course_name}</span>
          <span className="tag">{isSection ? `Section ${item.section_number}` : sourceLabel(item.kind)}</span>
          {isSection && item.pages > 0 && <span className="muted">{item.pages} p.</span>}
          {item.has_summary && <span className="tag ai">notes</span>}
          {item.questions > 0 && <span className="tag">{item.questions} cards</span>}
          {slot?.late && <span className="tag warn">late</span>}
        </div>
        {item.needed_by && (
          <div className={`small ${item.overdue ? "late" : "muted"}`}>
            {item.overdue ? "Overdue since " : isSection ? `Needed for “${item.needed_for}” by ` : "Due "}
            {when(item.needed_by)}
          </div>
        )}
      </div>
      <div className="plan-side">
        <strong>{minutes(slot ? slot.minutes_today : item.minutes)}</strong>
        {isSection && onStudied && (
          <button className="btn small ok" onClick={studied} disabled={busy}><Icon name="check" /> Studied</button>
        )}
        {!isSection && item.url && (
          <a className="btn small ghost" href={item.url} target="_blank" rel="noopener noreferrer">Moodle ↗</a>
        )}
      </div>
    </li>
  );
}

export default function Plan() {
  const [days, setDays] = useState(14);
  const { data, error, reload } = useLoad(() => api.plan(days), [days]);
  const [hours, setHours] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  if (!data) return <Status error={error} loading />;
  const h = hours ?? data.hours_per_day;

  async function saveHours(v: number) {
    setHours(v);
    setSaving(true);
    try {
      await api.setHours(v);
      reload();
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <p className="crumbs"><a href={href.dashboard}>← Today</a></p>
      <h1>Catch-up plan</h1>
      <p className="muted small">
        Sections you haven't studied and open deadlines, ordered by the deadline each one is needed for. Times are
        estimates from page counts. Mark a section studied to take it off the plan.
      </p>
      <div className="plan-controls">
        <label>
          Hours per day
          <select value={h} disabled={saving} onChange={(e) => saveHours(Number(e.target.value))}>
            {[0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8].concat(
              [0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8].includes(h) ? [] : [h]).sort((a, b) => a - b).map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          Days
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 14, 21, 30, 60].map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
      </div>
      <Summary plan={data} />
      {data.notes.map((n, i) => <p key={i} className="banner warn small">{n}</p>)}
      {!data.days.length && !data.unscheduled.length && (
        <p className="empty">Nothing left to catch up on. 🎉</p>
      )}
      {data.days.map((d) => (
        <section key={d.date}>
          <h2 className="day-head">
            <span>{dayLabel(d.date, data.today)}</span>
            <span className="muted small">{minutes(d.minutes)}</span>
          </h2>
          <ul className="plan-list">
            {d.items.map((it, i) => <PlanRow key={i} item={it} onStudied={reload} />)}
          </ul>
        </section>
      ))}
      {data.unscheduled.length > 0 && (
        <section>
          <h2 className="day-head">
            <span>Doesn't fit in {days} days</span>
            <span className="muted small">{minutes(data.unscheduled_minutes)}</span>
          </h2>
          <ul className="plan-list">
            {data.unscheduled.map((it, i) => <PlanRow key={i} item={it} onStudied={reload} />)}
          </ul>
        </section>
      )}
    </>
  );
}

function Summary({ plan }: { plan: PlanData }) {
  const total = plan.sections_left + plan.sections_done;
  return (
    <section className="summary" aria-label="Plan summary">
      <div className="stat static"><strong>{plan.sections_left}</strong><span>sections left</span></div>
      <div className="stat static"><strong>{minutes(plan.total_minutes)}</strong><span>of work</span></div>
      <div className={`stat static${plan.late ? " bad" : ""}`}>
        <strong>{total ? Math.round((100 * plan.sections_done) / total) : 0}%</strong>
        <span>{plan.late ? `${plan.late} late` : "caught up"}</span>
      </div>
    </section>
  );
}
