import { useState } from "react";
import { api, type Deadline } from "../api";
import { celebrate } from "./Confetti";
import { Icon } from "./Icon";
import { courseColor, fromNow, sourceLabel, when } from "../format";
import { href } from "../router";
import { PrefsMenu, PrefTags } from "./Prefs";

export function DeadlineItem({
  d,
  onChange,
  showCourse = true,
}: {
  d: Deadline;
  onChange?: (d: Deadline) => void;
  showCourse?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const now = Date.now() / 1000;
  const overdue = d.due_at < now && !d.done;

  async function toggle(e: React.MouseEvent<HTMLButtonElement>) {
    const button = e.currentTarget;
    setBusy(true);
    try {
      await api.setDone(d.id, !d.done);
      if (!d.done) celebrate(button, 60);
      onChange?.({ ...d, done: !d.done, done_by: d.done ? null : "you" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={`deadline${overdue && d.mandatory && !d.ignored ? " overdue" : ""}${d.done ? " done" : ""}${d.ignored ? " ignored" : ""}`}>
      <span className="swatch" style={{ background: courseColor(d.course_id) }} aria-hidden="true" />
      <div className="deadline-main">
        <div className="deadline-title">{d.name}</div>
        <div className="deadline-meta">
          {showCourse && d.course_id != null && (
            <a href={href.course(d.course_id)} className="course-link">
              {d.course_shortname || d.course_name}
            </a>
          )}
          <span className="tag">{sourceLabel(d.source)}</span>
          {d.closed && <span className="tag warn">closed</span>}
          <PrefTags state={d} />
          {d.done && <span className="tag ok pop">done{d.done_by === "moodle" ? " at the source" : ""}</span>}
        </div>
        <div className="deadline-when">
          <time dateTime={new Date(d.due_at * 1000).toISOString()}>{when(d.due_at)}</time>
          <span className={overdue && d.mandatory && !d.ignored ? "late" : "muted"}> · {fromNow(d.due_at)}</span>
        </div>
      </div>
      <div className="deadline-actions">
        {d.url && (
          <a className="btn small ghost" href={d.url} target="_blank" rel="noopener noreferrer">
            Source ↗
          </a>
        )}
        {d.done_by !== "moodle" && (
          <button className={`btn small ${d.done ? "ghost" : "ok"}`} onClick={toggle} disabled={busy}>
            {d.done ? "Undo" : <><Icon name="check" /> Done</>}
          </button>
        )}
        {!d.done && (
          <PrefsMenu state={d} label={d.name} save={(p) => api.setDeadlinePrefs(d.id, p)}
            onChange={(st) => onChange?.({ ...d, ...st, id: d.id })} />
        )}
      </div>
    </li>
  );
}

export function DeadlineList({
  items,
  empty,
  onChange,
  showCourse,
}: {
  items: Deadline[];
  empty: string;
  onChange?: (d: Deadline) => void;
  showCourse?: boolean;
}) {
  if (!items.length) return <p className="empty">{empty}</p>;
  return (
    <ul className="deadlines">
      {items.map((d) => (
        <DeadlineItem key={d.id} d={d} onChange={onChange} showCourse={showCourse} />
      ))}
    </ul>
  );
}
