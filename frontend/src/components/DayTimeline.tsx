import styled from "styled-components";
import type { BusySlot, Deadline, PlanDay, ScheduleSession } from "../api";
import { courseTitle } from "../format";
import { minutes } from "../pages/Plan";
import { IconButton } from "../ui";
import { clock } from "./ScheduleBlock";

// The phone's day view of the calendar: a compact week strip to pick the day, and that day's
// course sessions as a vertical timeline (no horizontal scrolling). Its tasks are listed by
// components/DayTasks.tsx under it.

export function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + n);
  return isoDay(d);
}

export function mondayOf(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  return addDays(iso, -((d.getDay() + 6) % 7));
}

export function longDate(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

const Strip = styled.nav`
  display: grid;
  grid-template-columns: 32px repeat(7, minmax(0, 1fr)) 32px;
  align-items: center;
  gap: 2px;
  & > button { min-width: 0; padding: 0; }
`;

const DayButton = styled.button<{ $today: boolean }>`
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  min-height: 52px;
  padding: 4px 0;
  border: 1px solid transparent;
  border-radius: ${({ theme }) => theme.radii.md};
  background: transparent;
  color: ${({ theme }) => theme.colors.textMain};
  font: inherit;
  cursor: pointer;
  & small { font-size: ${({ theme }) => theme.fontSizes.xs}; color: ${({ theme }) => theme.colors.textMuted}; text-transform: uppercase; }
  & strong { font-size: ${({ theme }) => theme.fontSizes.lg}; font-variant-numeric: tabular-nums; }
  & i { width: 6px; height: 6px; border-radius: 50%; background: transparent; }
  & i[data-on="true"] { background: ${({ theme }) => theme.colors.primary}; }
  ${({ $today, theme }) => ($today ? `& strong { color: ${theme.colors.primaryStrong}; }` : "")}
  &[aria-pressed="true"] {
    background: ${({ theme }) => theme.colors.primaryStrong};
    & small, & strong { color: ${({ theme }) => theme.colors.onPrimary}; }
    & i[data-on="true"] { background: ${({ theme }) => theme.colors.onPrimary}; }
  }
`;

export function DayStrip({ focus, today, days, onFocus }: {
  focus: string;
  today: string;
  days: Map<string, PlanDay>;
  onFocus: (iso: string) => void;
}) {
  const monday = mondayOf(focus);
  const week = Array.from({ length: 7 }, (_, i) => addDays(monday, i));
  return (
    <Strip aria-label="Pick a day">
      <IconButton type="button" aria-label="Previous week" onClick={() => onFocus(addDays(focus, -7))}>‹</IconButton>
      {week.map((d) => {
        const date = new Date(`${d}T12:00:00`);
        const planned = (days.get(d)?.session_ids.length ?? 0) > 0;
        return (
          <DayButton key={d} type="button" aria-pressed={d === focus} $today={d === today}
            aria-label={`${longDate(d)}${planned ? ", study planned" : ""}`} onClick={() => onFocus(d)}>
            <small>{date.toLocaleDateString(undefined, { weekday: "narrow" })}</small>
            <strong>{date.getDate()}</strong>
            <i data-on={planned} aria-hidden="true" />
          </DayButton>
        );
      })}
      <IconButton type="button" aria-label="Next week" onClick={() => onFocus(addDays(focus, 7))}>›</IconButton>
    </Strip>
  );
}

const Line = styled.ol`
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
`;

const Row = styled.li`
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 10px;
  align-items: stretch;
`;

const When = styled.div`
  padding-top: 8px;
  text-align: right;
  font-size: ${({ theme }) => theme.fontSizes.sm};
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  color: ${({ theme }) => theme.colors.textMuted};
  line-height: 1.3;
`;

const Slot = styled.button<{ $color: string; $past: boolean }>`
  display: block;
  width: 100%;
  min-height: ${({ theme }) => theme.layout.tap};
  padding: 8px 12px;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-left: 6px solid ${({ $color }) => $color};
  border-radius: ${({ theme }) => theme.radii.md};
  background: ${({ $color }) => `color-mix(in srgb, ${$color} 10%, var(--c-surface))`};
  color: ${({ theme }) => theme.colors.textMain};
  font: inherit;
  text-align: left;
  cursor: pointer;
  opacity: ${({ $past }) => ($past ? 0.6 : 1)};
  & strong { display: block; overflow-wrap: anywhere; }
  & span { font-size: ${({ theme }) => theme.fontSizes.sm}; color: ${({ theme }) => theme.colors.textMuted}; }
`;

const Quiet = styled.div<{ $dashed?: boolean }>`
  padding: 6px 12px;
  border: 1px ${({ $dashed }) => ($dashed ? "dashed" : "solid")} ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.md};
  font-size: ${({ theme }) => theme.fontSizes.sm};
  color: ${({ theme }) => theme.colors.textMuted};
  overflow-wrap: anywhere;
`;

const Pin = styled.button<{ $done: boolean }>`
  width: 100%;
  min-height: 36px;
  padding: 6px 12px;
  border: 1px dashed ${({ theme }) => theme.colors.borderStrong};
  border-radius: ${({ theme }) => theme.radii.md};
  background: transparent;
  color: ${({ theme }) => theme.colors.textMain};
  font: inherit;
  font-size: ${({ theme }) => theme.fontSizes.sm};
  text-align: left;
  overflow-wrap: anywhere;
  cursor: pointer;
  ${({ $done }) => ($done ? "text-decoration: line-through; opacity: .6;" : "")}
`;

type Entry =
  | { at: number; kind: "session"; s: ScheduleSession }
  | { at: number; kind: "busy"; b: BusySlot }
  | { at: number; kind: "deadline"; d: Deadline };

export function DayTimeline({ date, sessions, busy, deadlines, timeZone, onOpen, onDeadline }: {
  date: string;
  sessions: ScheduleSession[];
  busy: BusySlot[];
  deadlines: Deadline[];
  timeZone?: string;
  onOpen: (s: ScheduleSession) => void;
  onDeadline: (d: Deadline) => void;
}) {
  const entries: Entry[] = [
    ...sessions.filter((s) => s.date === date).map((s) => ({ at: s.start, kind: "session" as const, s })),
    ...busy.filter((b) => b.date === date).map((b) => ({ at: b.all_day ? 0 : b.start, kind: "busy" as const, b })),
    ...deadlines.map((d) => ({ at: d.due_at, kind: "deadline" as const, d })),
  ].sort((a, b) => a.at - b.at);
  if (!entries.length) return <Quiet $dashed>No study session this day.</Quiet>;
  const now = Date.now() / 1000;
  return (
    <Line aria-label={`Sessions on ${longDate(date)}`}>
      {entries.map((e) => {
        if (e.kind === "session") {
          const s = e.s;
          return (
            <Row key={s.id}>
              <When>{clock(s.start, timeZone)}<br />{clock(s.end, timeZone)}</When>
              <Slot type="button" $color={s.color} $past={s.end < now} onClick={() => onOpen(s)}>
                <strong>{s.label}</strong>
                <span>{minutes(s.minutes)}{s.task_keys.length > 1 ? ` · ${s.task_keys.length} tasks` : ""}{s.late ? " · late" : ""}</span>
              </Slot>
            </Row>
          );
        }
        if (e.kind === "busy") {
          const b = e.b;
          return (
            <Row key={`b${b.start}`}>
              <When>{b.all_day ? "All day" : clock(b.start, timeZone)}</When>
              <Quiet>{b.reason || "Unavailable"}{b.all_day ? "" : ` until ${clock(b.end, timeZone)}`}</Quiet>
            </Row>
          );
        }
        const d = e.d;
        return (
          <Row key={`d${d.id}`}>
            <When>{clock(d.due_at, timeZone)}</When>
            <Pin type="button" $done={d.done} onClick={() => onDeadline(d)}>
              📌 {d.course_name ? `${courseTitle(d.course_name)}: ` : ""}{d.name}
            </Pin>
          </Row>
        );
      })}
    </Line>
  );
}
