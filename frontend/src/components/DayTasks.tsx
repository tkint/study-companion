import styled from "styled-components";
import type { PlanDay, PlanTask, ScheduleSession } from "../api";
import { minutes } from "../pages/Plan";
import { Badge, Muted, Swatch } from "../ui";
import { clock } from "./ScheduleBlock";

// A day's tasks (backend: app/planner/tasks.py): what to accomplish, grouped by course, with
// a completion tick, priority, deadline and effort. Independent of the calendar's sessions:
// ticking a task never moves a session. Used beside the calendar (desktop), under the day's
// timeline (phone) and in a session's dialog.

const Group = styled.section`
  & + & { margin-top: 14px; }
`;

const GroupHead = styled.h3`
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 4px;
  font-size: ${({ theme }) => theme.fontSizes.md};
  font-weight: 700;
  overflow-wrap: anywhere;
  & > span:last-child {
    margin-left: auto;
    flex: none;
    font-weight: 600;
    font-size: ${({ theme }) => theme.fontSizes.xs};
    color: ${({ theme }) => theme.colors.textMuted};
    font-variant-numeric: tabular-nums;
  }
`;

export const TaskList = styled.ul`
  list-style: none;
  margin: 0;
  padding: 0;
`;

const Item = styled.li<{ $done: boolean }>`
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-height: ${({ theme }) => theme.layout.tap};
  padding: 6px 0;
  border-top: 1px solid ${({ theme }) => theme.colors.border};
  &:first-child { border-top: 0; }
  & input {
    flex: none;
    width: 20px;
    height: 20px;
    margin: 2px 0 0;
    accent-color: ${({ theme }) => theme.colors.success};
    cursor: pointer;
  }
  & .title {
    font-weight: 600;
    overflow-wrap: anywhere;
    ${({ $done, theme }) => ($done ? `text-decoration: line-through; color: ${theme.colors.textMuted};` : "")}
  }
`;

// The whole row is the checkbox's label, so the tap target is the full row.
const Tick = styled.label`
  display: flex;
  align-items: flex-start;
  gap: 10px;
  flex: 1 1 auto;
  min-width: 0;
  cursor: pointer;
`;

const Meta = styled.span`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 8px;
  margin-top: 2px;
  font-size: ${({ theme }) => theme.fontSizes.xs};
  color: ${({ theme }) => theme.colors.textMuted};
`;

const Open = styled.button`
  flex: none;
  min-width: 32px;
  min-height: 32px;
  border: 0;
  background: transparent;
  color: ${({ theme }) => theme.colors.textMuted};
  border-radius: ${({ theme }) => theme.radii.sm};
  cursor: pointer;
  &:hover { background: ${({ theme }) => theme.colors.surfaceSunken}; color: ${({ theme }) => theme.colors.textMain}; }
`;

export const PRIORITY_LABEL = { high: "High", medium: "Medium", low: "" } as const;

function dueLabel(t: PlanTask, timeZone?: string): string {
  if (!t.due) return "";
  const d = new Date(t.due * 1000);
  let day = "";
  try {
    day = d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", timeZone });
  } catch {
    day = d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  }
  const handIn = !(t.kind === "study" || t.kind === "reading" || t.kind === "review");
  if (handIn && t.due < Date.now() / 1000) return `Overdue since ${day}`;
  const what = handIn ? "Due" : "Needed by";
  return `${what} ${day} ${clock(t.due, timeZone)}`;
}

export function effort(t: PlanTask): string {
  if (t.kind === "reading") return t.pages ? `about ${t.pages} pages` : "";
  return t.minutes ? minutes(t.minutes) : "";
}

export function TaskRow({ task: t, done, onTick, onOpen, timeZone }: {
  task: PlanTask;
  done: boolean;
  onTick: (t: PlanTask, done: boolean) => void;
  onOpen?: (t: PlanTask) => void;
  timeZone?: string;
}) {
  const due = dueLabel(t, timeZone);
  const work = effort(t);
  return (
    <Item $done={done}>
      <Tick>
        <input type="checkbox" checked={done} onChange={(e) => onTick(t, e.target.checked)} />
        <span>
          <span className="title">{t.title}</span>
          <Meta>
            {t.part && <span>{t.part}</span>}
            {PRIORITY_LABEL[t.priority] && !done && (
              <Badge $tone={t.priority === "high" ? "danger" : "warning"}>{PRIORITY_LABEL[t.priority]}</Badge>
            )}
            {t.late && !done && <Badge $tone="warning">late</Badge>}
            {due && <span>{due}</span>}
            {work && <span>{work}</span>}
            {!t.session_id && t.kind === "reading" && <span>in your own time</span>}
          </Meta>
        </span>
      </Tick>
      {onOpen && (
        <Open type="button" onClick={() => onOpen(t)} aria-label={`Details: ${t.title}`} title="Details">›</Open>
      )}
    </Item>
  );
}

/** The sessions of a course that day, as "09:15–11:25". */
function times(sessions: ScheduleSession[], timeZone?: string): string {
  return sessions.map((s) => `${clock(s.start, timeZone)}–${clock(s.end, timeZone)}`).join(", ");
}

export function DayTasks({ day, sessions, done, onTick, onOpen, timeZone }: {
  day: PlanDay | undefined;
  /** All sessions (to show each course's times that day). */
  sessions: ScheduleSession[];
  done: (t: PlanTask) => boolean;
  onTick: (t: PlanTask, done: boolean) => void;
  onOpen?: (t: PlanTask) => void;
  timeZone?: string;
}) {
  if (!day || !day.tasks.length) return <Muted $small>Nothing planned this day.</Muted>;
  const byKey = new Map(day.tasks.map((t) => [t.key, t]));
  const today = sessions.filter((s) => s.date === day.date);
  return (
    <>
      {day.courses.map((c, i) => {
        const own = today.filter((s) => (s.kind === "flashcards" ? c.course_label === "Flashcards" && c.course_id == null
          : s.course_id === c.course_id));
        return (
          <Group key={`${c.course_id ?? "x"}-${i}`} aria-label={c.course_label || "Other"}>
            <GroupHead>
              <Swatch style={{ background: c.color }} aria-hidden="true" />
              <span>{c.course_label || "Other"}</span>
              <span>{own.length ? times(own, timeZone) : "no time slot"}</span>
            </GroupHead>
            <TaskList>
              {c.keys.map((k) => byKey.get(k)).filter((t): t is PlanTask => !!t).map((t) => (
                <TaskRow key={t.key} task={t} done={done(t)} onTick={onTick} onOpen={onOpen} timeZone={timeZone} />
              ))}
            </TaskList>
          </Group>
        );
      })}
    </>
  );
}
