import styled from "styled-components";
import type {
  DailyUnavailability, DatedUnavailability, ScheduleConfig, ScheduleCourse, WeeklyUnavailability,
} from "../api";
import { courseColor } from "../format";
import { minutes } from "../pages/Plan";
import {
  Button, Check, DetailsCard, Field, IconButton, Input, Muted, Select, Small, Swatch, Toggles,
} from "../ui";

// The settings of the timed study schedule (app/planner/schedule.py) as one form. The
// calendar page keeps the draft, previews it and saves it; saving publishes the schedule
// that the calendar feed shows.

const Grid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px 24px;
  margin: 10px 0;
`;

const SliderBox = styled.label`
  display: grid;
  align-content: start;
  gap: 4px;
  flex: 1;
  min-width: 0;
  font-size: ${({ theme }) => theme.fontSizes.md};
  & > span:first-child { display: flex; justify-content: space-between; gap: 8px; }
  & > span:first-child > strong { font-variant-numeric: tabular-nums; color: ${({ theme }) => theme.colors.primaryStrong}; }
  input[type="range"] {
    width: 100%;
    min-height: 28px;
    margin: 0;
    accent-color: ${({ theme }) => theme.colors.primary};
  }
`;

const CourseWeight = styled.div`
  display: flex;
  align-items: flex-start;
  gap: 10px;
  & > ${Swatch} { align-self: stretch; }
`;

const Inline = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 8px 0;
  & > ${Field} { margin-top: 0; min-width: 130px; }
`;

const Editor = styled.fieldset`
  display: grid;
  gap: 8px;
  margin: 14px 0 0;
  padding: 0;
  border: 0;
  min-width: 0;
  & > legend { padding: 0; font-weight: 700; }
  & > button { justify-self: start; }
`;

const Slot = styled.div<{ $past?: boolean }>`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  opacity: ${({ $past }) => ($past ? 0.6 : 1)};
  & ${Input}, & ${Select} { width: auto; min-height: 40px; }
  & ${Input}[type="text"] { flex: 1 1 140px; min-width: 0; }
`;

const Range = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 4px;
`;

const AllDay = styled(Check)`
  min-height: 40px;
  font-size: ${({ theme }) => theme.fontSizes.md};
`;

const WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const DayChecks = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
`;


function hours(h: number): string {
  return minutes(Math.round(h * 60));
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
    <SliderBox>
      <span>
        <span>{label}</span>
        <strong>{format(value)}</strong>
      </span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} />
      {hint && <Muted $small>{hint}</Muted>}
    </SliderBox>
  );
}

export function ScheduleForm({ draft: cfg, courses, today, onChange }: {
  draft: ScheduleConfig;
  courses: ScheduleCourse[];
  today: string;
  onChange: (next: ScheduleConfig) => void;
}) {
  function change(patch: Partial<ScheduleConfig>) {
    const next = { ...cfg, ...patch };
    if (next.daily_hours > next.max_daily_hours) next.daily_hours = next.max_daily_hours;
    onChange(next);
  }

  return (
    <>
      <DetailsCard open>
        <summary>Workload and rest</summary>
        <Grid>
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
        </Grid>
        <Inline>
          <Field>Study from
            <Input type="time" step={900} value={cfg.day_start}
              onChange={(e) => /^\d\d:\d\d$/.test(e.target.value) && change({ day_start: e.target.value })} />
          </Field>
          <Field>until
            <Input type="time" step={900} value={cfg.day_end === "24:00" ? "23:59" : cfg.day_end}
              onChange={(e) => /^\d\d:\d\d$/.test(e.target.value) && change({ day_end: e.target.value === "23:59" ? "24:00" : e.target.value })} />
          </Field>
          <Field>Start on
            <Input type="date" min={today} value={cfg.start_date > today ? cfg.start_date : today}
              onChange={(e) => change({ start_date: e.target.value > today ? e.target.value : "" })} />
          </Field>
          <Field>Plan ahead
            <Select value={cfg.days} onChange={(e) => change({ days: Number(e.target.value) })}>
              {[7, 14, 21, 30, 45, 60].concat([7, 14, 21, 30, 45, 60].includes(cfg.days) ? [] : [cfg.days])
                .sort((a, b) => a - b).map((v) => <option key={v} value={v}>{v} days</option>)}
            </Select>
          </Field>
        </Inline>
        {cfg.start_date > today && (
          <Small $muted>
            Nothing is planned before this day (a new term, back from holidays).{" "}
            <Button type="button" $variant="soft" $size="sm" onClick={() => change({ start_date: "" })}>Start today</Button>
          </Small>
        )}
        <Toggles>
          <Check><input type="checkbox" checked={cfg.recall} onChange={(e) => change({ recall: e.target.checked })} />
            Spaced active recall</Check>
          <Check><input type="checkbox" checked={cfg.include_optional} onChange={(e) => change({ include_optional: e.target.checked })} />
            Include optional work</Check>
          <Check><input type="checkbox" checked={cfg.beyond_target} onChange={(e) => change({ beyond_target: e.target.checked })} />
            Plan beyond my goal</Check>
        </Toggles>
      </DetailsCard>

      <DetailsCard open={courses.length > 1}>
        <summary>Course weights</summary>
        <Small $muted>A course with weight 2 gets about twice the time of one with weight 1. 0 leaves it out.
          Deadlines can still come first.</Small>
        <Grid>
          {courses.map((c) => {
            const w = cfg.course_weights[String(c.id)] ?? 1;
            return (
              <CourseWeight key={c.id}>
                <Swatch style={{ background: courseColor(c.id) }} aria-hidden="true" />
                <Slider label={c.shortname || c.fullname} value={w} min={0} max={3} step={0.25}
                  format={(v) => (v ? `×${v}` : "off")}
                  onChange={(v) => change({ course_weights: { ...cfg.course_weights, [String(c.id)]: v } })}
                  hint={`${Math.round(c.target_share)}% of the time, ${Math.round(c.planned_share)}% planned (${minutes(c.planned_minutes)})`} />
              </CourseWeight>
            );
          })}
        </Grid>
      </DetailsCard>

      <DetailsCard open={!cfg.weekly.length && !cfg.dates.length && !cfg.daily.length && !cfg.days_off.length}>
        <summary>Breaks and days off ({cfg.daily.length + cfg.days_off.length + cfg.weekly.length + cfg.dates.length})</summary>
        <DaysOffEditor days={cfg.days_off} onChange={(days_off) => change({ days_off })} />
        <DailyEditor rows={cfg.daily} onChange={(daily) => change({ daily })} />
        <WeeklyEditor rows={cfg.weekly} onChange={(weekly) => change({ weekly })} />
        <DatedEditor rows={cfg.dates} today={today} onChange={(dates) => change({ dates })} />
      </DetailsCard>

      <DetailsCard>
        <summary>Calendar feed</summary>
        <Toggles>
          <Check><input type="checkbox" checked={cfg.auto_update} onChange={(e) => change({ auto_update: e.target.checked })} />
            Update the plan every night with my progress and new deadlines</Check>
        </Toggles>
        <Small $muted>Without the nightly update, the calendar only changes when you save. Breaks and
          days off are not in the subscribed calendar: it only holds what you study and your deadlines.</Small>
      </DetailsCard>
    </>
  );
}

function DaysOffEditor({ days, onChange }: { days: number[]; onChange: (d: number[]) => void }) {
  return (
    <Editor>
      <legend>Days off</legend>
      <Small $muted>No study at all on these days.</Small>
      <DayChecks>
        {WEEKDAYS_SHORT.map((d, n) => (
          <Check key={n}>
            <input type="checkbox" checked={days.includes(n)}
              onChange={(e) => onChange(e.target.checked ? [...days, n].sort() : days.filter((x) => x !== n))} />
            {d}
          </Check>
        ))}
      </DayChecks>
    </Editor>
  );
}

function DailyEditor({ rows, onChange }: { rows: DailyUnavailability[]; onChange: (r: DailyUnavailability[]) => void }) {
  const set = (i: number, patch: Partial<DailyUnavailability>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <Editor>
      <legend>Every day</legend>
      <Small $muted>Meals, a walk, a nap…</Small>
      {rows.map((r, i) => (
        <Slot key={i}>
          <TimeRange start={r.start} end={r.end} onChange={(start, end) => set(i, { start, end })} />
          <Input type="text" aria-label="Reason" placeholder="Reason" maxLength={80}
            value={r.reason} onChange={(e) => set(i, { reason: e.target.value })} />
          <IconButton type="button" aria-label="Remove" onClick={() => onChange(rows.filter((_, j) => j !== i))}>✕</IconButton>
        </Slot>
      ))}
      <Button type="button" $variant="soft" $size="sm" disabled={rows.length >= 10}
        onClick={() => onChange([...rows, { start: "12:00", end: "14:00", reason: "Meal" }])}>+ Daily break</Button>
    </Editor>
  );
}

function WeeklyEditor({ rows, onChange }: { rows: WeeklyUnavailability[]; onChange: (r: WeeklyUnavailability[]) => void }) {
  const set = (i: number, patch: Partial<WeeklyUnavailability>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <Editor>
      <legend>Every week</legend>
      <Small $muted>Classes, work shifts, training…</Small>
      {rows.map((r, i) => (
        <Slot key={i}>
          <Select aria-label="Day" value={r.day} onChange={(e) => set(i, { day: Number(e.target.value) })}>
            {WEEKDAYS_SHORT.map((d, n) => <option key={n} value={n}>{d}</option>)}
          </Select>
          <TimeRange start={r.start} end={r.end} onChange={(start, end) => set(i, { start, end })} />
          <Input type="text" aria-label="Reason" placeholder="Reason" maxLength={80}
            value={r.reason} onChange={(e) => set(i, { reason: e.target.value })} />
          <IconButton type="button" aria-label="Remove" onClick={() => onChange(rows.filter((_, j) => j !== i))}>✕</IconButton>
        </Slot>
      ))}
      <Button type="button" $variant="soft" $size="sm" disabled={rows.length >= 50}
        onClick={() => onChange([...rows, { day: 0, start: "09:00", end: "12:00", reason: "" }])}>+ Weekly slot</Button>
    </Editor>
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
    <Editor>
      <legend>On specific days</legend>
      <Small $muted>Appointments, travel, days off…</Small>
      {sorted.map(({ r, i }) => {
        const allDay = r.start === "00:00" && r.end === "24:00";
        return (
          <Slot key={i} $past={r.date < today}>
            <Input type="date" aria-label="Date" value={r.date}
              onChange={(e) => e.target.value && set(i, { date: e.target.value })} />
            <AllDay>
              <input type="checkbox" checked={allDay}
                onChange={(e) => set(i, e.target.checked ? { start: "00:00", end: "24:00" } : { start: "09:00", end: "12:00" })} />
              all day
            </AllDay>
            {!allDay && <TimeRange start={r.start} end={r.end} onChange={(start, end) => set(i, { start, end })} />}
            <Input type="text" aria-label="Reason" placeholder="Reason" maxLength={80}
              value={r.reason} onChange={(e) => set(i, { reason: e.target.value })} />
            <IconButton type="button" aria-label="Remove" onClick={() => onChange(rows.filter((_, j) => j !== i))}>✕</IconButton>
          </Slot>
        );
      })}
      <Button type="button" $variant="soft" $size="sm" disabled={rows.length >= 100}
        onClick={() => onChange([...rows, { date: tomorrow, start: "00:00", end: "24:00", reason: "" }])}>+ Day off or appointment</Button>
    </Editor>
  );
}

function TimeRange({ start, end, onChange }: { start: string; end: string; onChange: (start: string, end: string) => void }) {
  const ok = (v: string) => /^\d\d:\d\d$/.test(v);
  return (
    <Range>
      <Input type="time" aria-label="From" step={900} value={start}
        onChange={(e) => ok(e.target.value) && onChange(e.target.value, end)} />
      <span aria-hidden="true">–</span>
      <Input type="time" aria-label="Until" step={900} value={end === "24:00" ? "23:59" : end}
        onChange={(e) => ok(e.target.value) && onChange(start, e.target.value === "23:59" ? "24:00" : e.target.value)} />
    </Range>
  );
}
