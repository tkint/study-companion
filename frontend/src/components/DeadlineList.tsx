import { useState } from "react";
import { api, type Deadline } from "../api";
import { courseColor, fromNow, sourceLabel, when } from "../format";
import { href } from "../router";

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

  async function toggle() {
    setBusy(true);
    try {
      await api.setDone(d.id, !d.done);
      onChange?.({ ...d, done: !d.done, done_by: d.done ? null : "you" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={`deadline${overdue ? " overdue" : ""}${d.done ? " done" : ""}`}>
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
          {d.done && <span className="tag ok">done{d.done_by === "moodle" ? " in Moodle" : ""}</span>}
        </div>
        <div className="deadline-when">
          <time dateTime={new Date(d.due_at * 1000).toISOString()}>{when(d.due_at)}</time>
          <span className={overdue ? "late" : "muted"}> · {fromNow(d.due_at)}</span>
        </div>
      </div>
      <div className="deadline-actions">
        {d.url && (
          <a className="btn small ghost" href={d.url} target="_blank" rel="noopener noreferrer">
            Moodle ↗
          </a>
        )}
        {d.done_by !== "moodle" && (
          <button className="btn small ghost" onClick={toggle} disabled={busy}>
            {d.done ? "Undo" : "Mark done"}
          </button>
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
