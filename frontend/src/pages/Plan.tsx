import { useState } from "react";
import { api, type Plan as PlanData, type PlanItem, type PlanSlot } from "../api";
import { Progress, Status, useLoad } from "../components/common";
import { celebrate } from "../components/Confetti";
import { Icon } from "../components/Icon";
import { PrefsMenu } from "../components/Prefs";
import { courseColor, sourceLabel, when } from "../format";
import { href } from "../router";

// The rule-based catch-up plan (app/planner): the mandatory sections left to study and open
// deadlines, ordered by urgency and spread over the days at your hours per day. Backlog
// beyond your catch-up target (e.g. 60%) is listed apart, as "if you have time".

const TARGETS = [40, 50, 60, 70, 80, 90, 100];

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

export function PlanRow({ item, onStudied, onPrefs }: {
  item: PlanSlot | PlanItem;
  onStudied?: (sectionId: number) => void;
  onPrefs?: () => void;
}) {
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
          {!item.mandatory && <span className="tag muted-tag">optional</span>}
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
          <button className="btn btn-sm btn-success" onClick={studied} disabled={busy}><Icon name="check" /> Studied</button>
        )}
        {!isSection && item.url && (
          <a className="btn btn-sm btn-ghost" href={item.url} target="_blank" rel="noopener noreferrer">Source ↗</a>
        )}
        {onPrefs && (item.section_id || item.deadline_id) && (
          <PrefsMenu state={{ mandatory: item.mandatory, ignored: false }} label={item.title} onChange={onPrefs}
            save={(p) => (item.section_id ? api.setSectionPrefs(item.section_id, p) : api.setDeadlinePrefs(item.deadline_id!, p))} />
        )}
      </div>
    </li>
  );
}

export default function Plan() {
  const [days, setDays] = useState(14);
  const [optional, setOptional] = useState(false);
  const [beyond, setBeyond] = useState(false);
  const { data, error, reload } = useLoad(() => api.plan(days, undefined, { optional, beyond }), [days, optional, beyond]);
  const [hours, setHours] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  if (!data) return <Status error={error} loading />;
  const h = hours ?? data.hours_per_day;
  const target = data.target_percent;

  async function saveTarget(v: number) {
    setSaving(true);
    try {
      await api.setTarget(v);
      reload();
    } finally {
      setSaving(false);
    }
  }

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
        The mandatory work ahead of you, ordered by the deadline each piece is needed for, plus enough of what you
        missed to reach your goal. You don't have to catch up on everything. Times are estimates from page counts;
        use ⋯ to mark something optional or let it go.
      </p>
      <p className="small">
        <a className="btn btn-sm" href={href.schedule}>Timed schedule and .ics export →</a>
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
        <label>
          Catch-up goal
          <select value={target} disabled={saving} onChange={(e) => saveTarget(Number(e.target.value))}>
            {TARGETS.concat(TARGETS.includes(target) ? [] : [target]).sort((a, b) => a - b).map((v) => (
              <option key={v} value={v}>{v}%</option>
            ))}
          </select>
        </label>
      </div>
      <div className="view-toggles">
        <label><input type="checkbox" checked={optional} onChange={(e) => setOptional(e.target.checked)} />
          Include optional work</label>
        <label><input type="checkbox" checked={beyond} onChange={(e) => setBeyond(e.target.checked)} />
          Plan beyond my goal</label>
      </div>
      <Summary plan={data} />
      <TargetBar plan={data} />
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
            {d.items.map((it, i) => <PlanRow key={i} item={it} onStudied={reload} onPrefs={reload} />)}
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
            {data.unscheduled.map((it, i) => <PlanRow key={i} item={it} onStudied={reload} onPrefs={reload} />)}
          </ul>
        </section>
      )}
      {data.beyond_target.length > 0 && (
        <details className="past">
          <summary>
            Beyond your {target}% goal: {data.beyond_target.length} item{data.beyond_target.length === 1 ? "" : "s"},{" "}
            {minutes(data.beyond_target_minutes)} (only if you have time)
          </summary>
          <ul className="plan-list">
            {data.beyond_target.map((it, i) => <PlanRow key={i} item={it} onStudied={reload} onPrefs={reload} />)}
          </ul>
        </details>
      )}
    </>
  );
}

function Summary({ plan }: { plan: PlanData }) {
  const p = plan.progress;
  return (
    <section className="summary" aria-label="Plan summary">
      <div className="stat static"><strong>{Math.round(p.percent)}%</strong><span>caught up</span></div>
      <div className="stat static"><strong>{Math.round(plan.projected_percent)}%</strong><span>with this plan</span></div>
      <div className={`stat static${plan.late ? " bad" : ""}`}>
        <strong>{minutes(plan.total_minutes)}</strong>
        <span>{plan.late ? `${plan.late} late` : "planned"}</span>
      </div>
    </section>
  );
}

// Progress on the mandatory work, with a mark at your goal.
function TargetBar({ plan }: { plan: PlanData }) {
  const p = plan.progress;
  const left = p.left_minutes_to_target;
  return (
    <div className="target-bar">
      <div className="target-progress">
        <Progress value={p.percent} />
        <span className="target-mark" style={{ left: `${p.target_percent}%` }} aria-hidden="true" />
      </div>
      <p className="small muted">
        {p.reached
          ? `Goal reached: ${Math.round(p.percent)}% of the mandatory work is done (goal ${p.target_percent}%). Anything more is a bonus.`
          : `${p.done_items} of ${p.total_items} mandatory items done. ${minutes(left)} more to reach your ${p.target_percent}% goal.`}
        {plan.ignored > 0 && ` ${plan.ignored} ignored.`}
        {plan.optional_left_out > 0 && ` ${plan.optional_left_out} optional left out.`}
      </p>
    </div>
  );
}
