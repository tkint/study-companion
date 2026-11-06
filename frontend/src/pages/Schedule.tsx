import { useEffect, useRef, useState } from "react";
import styled from "styled-components";
import {
  api, type DatedUnavailability, type Schedule as ScheduleData, type ScheduleBlock, type ScheduleConfig,
  type WeeklyUnavailability,
} from "../api";
import { Status, useLoad } from "../components/common";
import { courseColor } from "../format";
import { href } from "../router";
import { DayHead, minutes, PlanRow } from "./Plan";
import { WorkMain, WorkRow, WorkTitle } from "../components/DeadlineList";
import type { Tone } from "../styles/theme";
import {
  Alert, Badge, Button, Check, Crumbs, DetailsCard, Empty, Field, IconButton, Input, Late, Lead, List, Meta, Muted,
  Row, Select, Small, Stat, StatGrid, Swatch, Toggles,
} from "../ui";

const Grid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px 24px;
  margin: 10px 0;
`;

const SliderBox = styled.label`
  display: grid;
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

const Blocked = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 8px;
`;

const Time = styled.div`
  font-size: ${({ theme }) => theme.fontSizes.sm};
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  color: ${({ theme }) => theme.colors.textMuted};
`;

const Detail = styled(Small)`
  white-space: pre-line;
`;

const Files = styled.p`
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin: 4px 0 0;
  font-size: ${({ theme }) => theme.fontSizes.sm};
`;

const Minutes = styled.strong`
  flex: none;
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
`;

// The timed study schedule (app/planner/schedule.py): the catch-up plan's work as focus blocks
// with times, around your weekly and dated unavailabilities, within your hours per day, rest
// hours and daily maximum. Changes save on their own and the schedule is generated again.
// "Download .ics" exports the blocks for Google Calendar, Apple Calendar or Outlook.

const WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const SAVE_DELAY = 600;

const KIND_TONE: Record<ScheduleBlock["kind"], Tone> = {
  deep: "neutral",
  practice: "warning",
  recall: "primary",
  flashcards: "success",
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
      <Crumbs><a href={href.plan}>← Catch-up plan</a></Crumbs>
      <h1>Study schedule</h1>
      <Lead $small>
        Your catch-up plan with times: focus blocks around your classes and commitments, short breaks in between,
        active recall a day and a few days after each section, and a margin before every deadline. Change anything
        below and the schedule updates.
      </Lead>
      <Row>
        <Button as="a" $variant="primary" $size="sm" href="/api/schedule.ics" download>Download .ics</Button>
        <Muted $small role="status">
          {saveState.busy ? "Saving…" : saveState.error ? <Late>{saveState.error}</Late> : "Saved"}
        </Muted>
      </Row>

      <Summary data={data} />
      {data.notes.map((n, i) => <Alert key={i} $tone="warning">{n}</Alert>)}

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
          <Field>Plan ahead
            <Select value={cfg.days} onChange={(e) => change({ days: Number(e.target.value) })}>
              {[7, 14, 21, 30, 45, 60].concat([7, 14, 21, 30, 45, 60].includes(cfg.days) ? [] : [cfg.days])
                .sort((a, b) => a - b).map((v) => <option key={v} value={v}>{v} days</option>)}
            </Select>
          </Field>
        </Inline>
        <Toggles>
          <Check><input type="checkbox" checked={cfg.recall} onChange={(e) => change({ recall: e.target.checked })} />
            Spaced active recall</Check>
          <Check><input type="checkbox" checked={cfg.include_optional} onChange={(e) => change({ include_optional: e.target.checked })} />
            Include optional work</Check>
          <Check><input type="checkbox" checked={cfg.beyond_target} onChange={(e) => change({ beyond_target: e.target.checked })} />
            Plan beyond my goal</Check>
        </Toggles>
      </DetailsCard>

      <DetailsCard open={data.courses.length > 1}>
        <summary>Course weights</summary>
        <Small $muted>A course with weight 2 gets about twice the time of one with weight 1. 0 leaves it out.
          Deadlines can still come first.</Small>
        <Grid>
          {data.courses.map((c) => {
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

      <DetailsCard open={!cfg.weekly.length && !cfg.dates.length}>
        <summary>When you can't study ({cfg.weekly.length + cfg.dates.length})</summary>
        <WeeklyEditor rows={cfg.weekly} onChange={(weekly) => change({ weekly })} />
        <DatedEditor rows={cfg.dates} today={data.today} onChange={(dates) => change({ dates })} />
      </DetailsCard>

      {!data.days.length && !data.unscheduled.length && <Empty>Nothing to schedule.</Empty>}
      {data.days.map((d) => (
        <section key={d.date}>
          <DayHead>
            <span>{dayLabel(d.date, data.today)}</span>
            <span>
              {minutes(d.minutes)}{d.stretched && <> <Badge $tone="warning">extra</Badge></>}
            </span>
          </DayHead>
          {d.blocked.length > 0 && (
            <Blocked>
              {d.blocked.map((b, i) => (
                <Badge key={i} $dashed>
                  {b.start === "00:00" && b.end === "24:00" ? "all day" : `${b.start}–${b.end}`}
                  {b.reason ? ` · ${b.reason}` : ""}
                </Badge>
              ))}
            </Blocked>
          )}
          {d.blocks.length ? (
            <List $gap="8px">{d.blocks.map((b, i) => <BlockRow key={i} block={b} timeZone={data.timezone} />)}</List>
          ) : (
            <Small $muted>No study blocks.</Small>
          )}
        </section>
      ))}
      {data.unscheduled.length > 0 && (
        <section>
          <DayHead>
            <span>Doesn't fit in {cfg.days} days</span>
            <span>{minutes(data.unscheduled_minutes)}</span>
          </DayHead>
          <List $gap="8px">
            {data.unscheduled.map((it, i) => <PlanRow key={i} item={it} />)}
          </List>
        </section>
      )}
    </>
  );
}

const SummaryGrid = styled(StatGrid)`
  grid-template-columns: repeat(4, minmax(0, 1fr));
  @media (max-width: 640px) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
`;

function Summary({ data }: { data: ScheduleData }) {
  const k = data.minutes_by_kind;
  return (
    <SummaryGrid aria-label="Schedule summary">
      <Stat $tone="primary"><strong>{minutes(data.total_minutes)}</strong><span>planned</span></Stat>
      <Stat><strong>{minutes((k.deep ?? 0) + (k.practice ?? 0))}</strong><span>reading and practice</span></Stat>
      <Stat><strong>{minutes((k.recall ?? 0) + (k.flashcards ?? 0))}</strong><span>recall and cards</span></Stat>
      <Stat $tone={data.late ? "danger" : undefined}>
        <strong>{data.late}</strong><span>late</span>
      </Stat>
    </SummaryGrid>
  );
}

function BlockRow({ block: b, timeZone }: { block: ScheduleBlock; timeZone?: string }) {
  const link = b.course_id ? href.course(b.course_id, b.section_id ?? undefined)
    : b.kind === "flashcards" ? href.study({ due: true }) : undefined;
  return (
    <WorkRow as="li" $late={b.late}>
      <Swatch style={{ background: b.course_id ? courseColor(b.course_id) : "var(--c-primary)" }} aria-hidden="true" />
      <WorkMain>
        <Time>{clock(b.start, timeZone)}–{clock(b.end, timeZone)}</Time>
        <WorkTitle>
          {link ? <a href={link}>{b.title}</a> : b.title}
          {b.parts > 1 && <Muted> · {b.kind === "recall" ? "review" : "part"} {b.part}/{b.parts}</Muted>}
        </WorkTitle>
        <Meta>
          {(b.course_short || b.course_name) && <strong>{b.course_short || b.course_name}</strong>}
          <Badge $tone={KIND_TONE[b.kind]}>{b.label}</Badge>
          {b.late && <Badge $tone="warning">late</Badge>}
        </Meta>
        {b.detail && <Detail $muted>{b.detail}</Detail>}
        {b.files.length > 0 && (
          <Files>
            {b.files.map((f) => (
              <a key={f.id} href={href.file(f.id, b.course_id ?? undefined)}>{f.name}{f.pages ? ` (${f.pages} p.)` : ""}</a>
            ))}
          </Files>
        )}
      </WorkMain>
      <Minutes>{minutes(b.minutes)}</Minutes>
    </WorkRow>
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
