import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import styled from "styled-components";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import type { DatesSetArg, DayCellContentArg, DayHeaderContentArg, EventClickArg, EventContentArg, EventInput, EventSourceFuncArg } from "@fullcalendar/core";
import { api, type Deadline, type PlanDay, type PlanTask, type Schedule, type ScheduleConfig, type ScheduleSession } from "../api";
import { Status } from "../components/common";
import { CalendarFeed } from "../components/CalendarFeed";
import { DayTasks } from "../components/DayTasks";
import { addDays, DayStrip, DayTimeline, isoDay, longDate } from "../components/DayTimeline";
import { EventDialog, type Selected } from "../components/EventDialog";
import { ExportWeeks } from "../components/ExportWeeks";
import { ReminderSettings } from "../components/Reminders";
import { clock, Summary } from "../components/ScheduleBlock";
import { ScheduleForm } from "../components/ScheduleForm";
import { courseColor, courseTitle } from "../format";
import { minutes, PlanRow } from "./Plan";
import {
  Alert, Banner, Button, Card, Check, DetailsCard, Dropdown, IconButton, Late, Lead, List, MenuItem, Modal, Muted, Row,
  Segmented, Small,
} from "../ui";

// One calendar for everything (issue: unified study calendar): the published study plan
// (app/planner/published.py) in two parts. The calendar is for time: one block per course
// session, Moodle deadlines and your unavailabilities. The focused day's task list is for
// doing: what to accomplish that day, grouped by course, with ticks (app/planner/tasks.py).
// Desktop: calendar on the left, the focused day's tasks on the right. Phone: a week strip,
// the day's timeline, then its tasks (or a Schedule / Tasks switch).
// The schedule settings are a form: changes show at once as a preview, and Save publishes
// them, which is what the subscribed feed (/calendar.ics) and the exports show. Subscribe, or
// Export (menu): as PDF or Excel, both built by the server, or ICS.

// FullCalendar's own CSS, re-coloured with the theme.
const CalendarCard = styled.div`
  padding: 10px;
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.lg};
  box-shadow: ${({ theme }) => theme.shadows.card};
  --fc-border-color: ${({ theme }) => theme.colors.border};
  --fc-page-bg-color: ${({ theme }) => theme.colors.surface};
  --fc-neutral-bg-color: ${({ theme }) => theme.colors.surfaceSunken};
  --fc-list-event-hover-bg-color: ${({ theme }) => theme.colors.surfaceSunken};
  --fc-today-bg-color: transparent;
  --fc-now-indicator-color: ${({ theme }) => theme.colors.danger};
  --fc-bg-event-color: ${({ theme }) => theme.colors.textMuted};
  --fc-bg-event-opacity: .14;
  --fc-button-bg-color: ${({ theme }) => theme.colors.surface};
  --fc-button-border-color: ${({ theme }) => theme.colors.border};
  --fc-button-text-color: ${({ theme }) => theme.colors.textMain};
  --fc-button-hover-bg-color: ${({ theme }) => theme.colors.surfaceSunken};
  --fc-button-hover-border-color: ${({ theme }) => theme.colors.borderStrong};
  --fc-button-active-bg-color: ${({ theme }) => theme.colors.primaryStrong};
  --fc-button-active-border-color: ${({ theme }) => theme.colors.primaryStrong};
  a { color: inherit; }
  .fc .fc-button { border-radius: ${({ theme }) => theme.radii.sm}; font-weight: 600; text-transform: none; box-shadow: none; }
  .fc .fc-button-primary:not(:disabled).fc-button-active { color: ${({ theme }) => theme.colors.onPrimary}; }
  .fc .fc-toolbar { flex-wrap: wrap; gap: 8px; }
  .fc .fc-toolbar-title { font-size: 1.15rem; font-weight: 750; }
  .fc .fc-col-header-cell-cushion { font-weight: 650; color: ${({ theme }) => theme.colors.textMuted}; }
  .fc-event { cursor: pointer; border-radius: 6px; }
  .fc-bg-event { cursor: default; }
  .fc .fc-bg-event .fc-event-title { font-size: .72rem; font-style: italic; color: ${({ theme }) => theme.colors.textMuted}; }
  .fc-done { opacity: .5; text-decoration: line-through; }
  .fc-overdue .fc-event-title, .fc-overdue .fc-list-event-title { font-weight: 700; }
  .fc-timegrid-event.fc-deadline, .fc-daygrid-event.fc-deadline { border-style: dashed; font-weight: 650; }
  .fc .fc-timegrid-slot { height: 2.1em; }
  .fc .fc-session { overflow: hidden; line-height: 1.25; padding: 1px 2px; }
  .fc .fc-session strong { display: block; font-size: .78rem; font-weight: 700; overflow-wrap: anywhere; }
  .fc .fc-session span { display: block; font-size: .7rem; opacity: .9; font-variant-numeric: tabular-nums; }
  .fc .fc-day-today .fc-col-header-cell-cushion, .fc .fc-day-today .fc-daygrid-day-number { color: ${({ theme }) => theme.colors.primaryStrong}; }
  .fc .fc-focused { background: color-mix(in srgb, ${({ theme }) => theme.colors.primary} 9%, transparent); }
  .fc th.fc-focused { box-shadow: inset 0 -3px 0 ${({ theme }) => theme.colors.primary}; }
  .fc th.fc-focused .fc-col-header-cell-cushion { color: ${({ theme }) => theme.colors.primaryStrong}; }
  .fc .fc-col-header-cell-cushion, .fc .fc-daygrid-day-number { cursor: pointer; }
  .fc-flashcards { opacity: .85; }
  .fc-late { outline: 2px solid ${({ theme }) => theme.colors.warning}; }
  &[data-preview="true"] .fc-study { opacity: .75; border-style: dashed; }
  ${({ theme }) => theme.media.phone} {
    padding: 6px;
    .fc .fc-header-toolbar { flex-wrap: wrap; justify-content: space-between; }
    .fc .fc-toolbar-chunk:nth-child(2) { order: -1; width: 100%; text-align: center; }
    .fc .fc-toolbar-chunk { display: flex; gap: 4px; }
    .fc .fc-button { padding: .4em .6em; }
  }
`;

// The dialog's footer stays at the bottom of the sheet while the form scrolls.
const SaveBar = styled(Banner)`
  position: sticky;
  z-index: 2;
  bottom: 0;
  margin: 4px 0 0;
  box-shadow: ${({ theme }) => theme.shadows.pop};
  background: ${({ theme }) => theme.colors.surface};
`;

const DialogHead = styled.div`
  & > h2 { margin: 0 0 4px; }
`;



// Desktop: calendar and the focused day's tasks side by side, the calendar wider.
const Split = styled.div`
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  ${({ theme }) => theme.media.desktop} {
    grid-template-columns: minmax(0, 7fr) minmax(300px, 3fr);
  }
`;

const Side = styled(Card)`
  ${({ theme }) => theme.media.desktop} {
    position: sticky;
    top: calc(${({ theme }) => theme.layout.topbar} + 12px);
    max-height: calc(100vh - ${({ theme }) => theme.layout.topbar} - 24px);
    overflow-y: auto;
    overscroll-behavior: contain;
  }
`;

const DayHead = styled.header`
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 4px;
  & h2 { flex: 1 1 auto; margin: 0; font-size: ${({ theme }) => theme.fontSizes.lg}; text-align: center; }
`;

const DaySub = styled(Muted)`
  display: block;
  margin-bottom: 10px;
  text-align: center;
`;

const PhoneStack = styled.div`
  display: grid;
  gap: 12px;
`;

const PHONE = "(max-width: 640px)";

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia(PHONE).matches);
  useEffect(() => {
    const m = window.matchMedia(PHONE);
    const on = () => setNarrow(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return narrow;
}

// The view you picked last opens next time (per device; week by default).
const VIEW_KEY = "calendar-view";
const VIEWS = ["timeGridWeek", "timeGridDay", "dayGridMonth"];
const PHONE_VIEW_KEY = "calendar-phone-view";
type PhoneView = "day" | "schedule" | "tasks";

function load(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // private mode: just don't remember
  }
}

const BREAKS_KEY = "calendar-breaks";

/** The ``at`` of a feed link (#/calendar?at=<timestamp>): the entry to open. */
function focusAt(): number | null {
  const query = window.location.hash.split("?")[1] ?? "";
  const at = new URLSearchParams(query).get("at");
  return at && /^\d{9,11}$/.test(at) ? Number(at) : null;
}

function lastView(): string {
  const v = load(VIEW_KEY);
  return v && VIEWS.includes(v) ? v : "timeGridWeek";
}
const PREVIEW_DELAY = 600;

/** A session block: the course (identifier and name), then its times and duration. No
 * tasks in it: they are in the day's task list. */
function sessionContent(arg: EventContentArg) {
  const s = arg.event.extendedProps.session as ScheduleSession | undefined;
  if (!s) return true; // FullCalendar's own rendering
  const tz = arg.event.extendedProps.timeZone as string | undefined;
  if (s.minutes < 40) {
    // A short session: one line, the course identifier and the times.
    return (
      <div className="fc-session" title={`${s.label}\n${clock(s.start, tz)}–${clock(s.end, tz)} · ${minutes(s.minutes)}`}>
        <span><b>{s.course_code || s.label}</b> {clock(s.start, tz)}–{clock(s.end, tz)}</span>
      </div>
    );
  }
  return (
    <div className="fc-session" title={`${s.label}\n${clock(s.start, tz)}–${clock(s.end, tz)} · ${minutes(s.minutes)}`}>
      <strong>{s.label}</strong>
      <span>{clock(s.start, tz)}–{clock(s.end, tz)} · {minutes(s.minutes)}</span>
    </div>
  );
}

function sessionEvent(s: ScheduleSession, timeZone: string): EventInput {
  return {
    id: s.id,
    title: s.label,
    start: new Date(s.start * 1000),
    end: new Date(s.end * 1000),
    color: s.color,
    classNames: ["fc-study", `fc-${s.kind}`, ...(s.late ? ["fc-late"] : []), ...(s.end * 1000 < Date.now() ? ["fc-done"] : [])],
    extendedProps: { session: s, timeZone },
  };
}

function deadlineEvent(d: Deadline): EventInput {
  return {
    id: `d${d.id}`,
    title: `📌 ${d.course_name ? courseTitle(d.course_name) + " - " : ""}${d.name}`,
    start: new Date(d.due_at * 1000),
    allDay: false,
    color: courseColor(d.course_id),
    classNames: ["fc-deadline", ...(d.done ? ["fc-done"] : d.due_at * 1000 < Date.now() ? ["fc-overdue"] : [])],
    extendedProps: { deadline: d },
  };
}

function same(a: ScheduleConfig, b: ScheduleConfig): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function savedAt(ts: number | null): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function dayStart(iso: string): number {
  return Math.floor(new Date(`${iso}T00:00:00`).getTime() / 1000);
}

/** "3 of 5 tasks left · 2 h 15 planned". */
function daySummary(day: PlanDay | undefined, isDone: (t: PlanTask) => boolean): string {
  if (!day) return "";
  const left = day.tasks.filter((t) => !isDone(t)).length;
  const parts = [day.tasks.length ? `${left} of ${day.tasks.length} task${day.tasks.length === 1 ? "" : "s"} left` : ""];
  if (day.minutes) parts.push(`${minutes(day.minutes)} planned`);
  return parts.filter(Boolean).join(" · ");
}

export default function Calendar() {
  const ref = useRef<FullCalendar>(null);
  const [saved, setSaved] = useState<Schedule | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draft, setDraft] = useState<ScheduleConfig | null>(null);
  const [preview, setPreview] = useState<Schedule | null>(null);
  const [state, setState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
  const [selected, setSelected] = useState<Selected | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"settings" | "subscribe" | "pdf" | "xlsx" | null>(null);
  const [visible, setVisible] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const narrow = useNarrow();
  const initialView = useMemo(() => lastView(), []);
  const [exportOpen, setExportOpen] = useState(false);
  const [showBreaks, setShowBreaks] = useState(() => load(BREAKS_KEY) !== "0");
  // The focused day (YYYY-MM-DD): its tasks are listed, the calendar highlights it.
  const [focus, setFocus] = useState<string>(() => isoDay(new Date()));
  const range = useRef<{ start: string; end: string } | null>(null);
  const [ticks, setTicks] = useState<Record<string, boolean>>({});
  const [tickError, setTickError] = useState<string | null>(null);
  const [phoneView, setPhoneView] = useState<PhoneView>(() => {
    const v = load(PHONE_VIEW_KEY);
    return v === "schedule" || v === "tasks" ? v : "day";
  });
  const [dayDeadlines, setDayDeadlines] = useState<Deadline[]>([]);
  const [deadlineVersion, setDeadlineVersion] = useState(0);

  useEffect(() => {
    api.schedule()
      .then((s) => {
        setSaved(s);
        setDraft(s.config);
        setFocus(s.start && s.start > s.today ? s.start : s.today);
      })
      .catch((e: Error) => setLoadError(e.message));
  }, []);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const dirty = !!(saved && draft && !same(saved.config, draft));
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const shown = (dirty && preview) || saved;
  const timeZone = shown?.timezone ?? "";

  // A plan that starts later (start date in the settings) opens on its first day.
  const startsOn = shown && shown.start && shown.start > shown.today ? shown.start : null;
  useEffect(() => {
    if (startsOn) setFocus(startsOn);
  }, [startsOn]);

  // The calendar follows the focused day when it is outside the period shown.
  useEffect(() => {
    const r = range.current;
    if (!r || focus < r.start || focus >= r.end) ref.current?.getApi().gotoDate(focus);
  }, [focus, narrow]);

  // A link from the subscribed calendar opens its entry (or the day of its deadline).
  useEffect(() => {
    if (!saved) return;
    const open = () => {
      const at = focusAt();
      if (at === null) return;
      const session = (saved.sessions ?? []).find((g) => g.start <= at && at < g.end);
      setFocus(session ? session.date : isoDay(new Date(at * 1000)));
      setDialog(null);
      setSelected(session ? { session } : null);
      window.history.replaceState(null, "", "#/calendar");
    };
    open();
    window.addEventListener("hashchange", open);
    return () => window.removeEventListener("hashchange", open);
  }, [saved]);

  const days = useMemo(() => new Map((shown?.plan_days ?? []).map((d) => [d.date, d])), [shown]);
  const sessions = useMemo(() => shown?.sessions ?? [], [shown]);
  const isDone = useCallback((t: PlanTask) => ticks[t.key] ?? t.done, [ticks]);

  // The phone's timeline shows the focused day's deadlines.
  useEffect(() => {
    if (!narrow) return;
    let live = true;
    const start = dayStart(focus);
    api.deadlines(start, dayStart(addDays(focus, 1)))
      .then((items) => { if (live) setDayDeadlines(items); })
      .catch(() => { if (live) setDayDeadlines([]); });
    return () => { live = false; };
  }, [narrow, focus, deadlineVersion]);

  const scheduleEvents = useMemo<EventInput[]>(() => {
    if (!shown) return [];
    const blocks = sessions.map((s) => sessionEvent(s, timeZone));
    const busy = (showBreaks ? shown.busy : []).map((u) => ({
      id: `u${u.start}`,
      title: u.reason || "Unavailable",
      start: u.all_day ? u.date : new Date(u.start * 1000),
      end: u.all_day ? undefined : new Date(u.end * 1000),
      allDay: u.all_day,
      display: "background",
    }));
    return [...blocks, ...busy];
  }, [shown, sessions, showBreaks, timeZone]);

  const deadlineSource = useCallback(async (info: EventSourceFuncArg) => {
    try {
      const items = await api.deadlines(Math.floor(info.start.getTime() / 1000), Math.ceil(info.end.getTime() / 1000));
      setError(null);
      return items.map(deadlineEvent);
    } catch (e) {
      setError((e as Error).message);
      return [];
    }
  }, []);
  const eventSources = useMemo(() => [{ id: "deadlines", events: deadlineSource }], [deadlineSource]);

  const close = useCallback(() => setSelected(null), []);
  const closeDialog = useCallback(() => setDialog(null), []);

  const refetchDeadlines = useCallback(() => {
    ref.current?.getApi().getEventSourceById("deadlines")?.refetch();
    setDeadlineVersion((v) => v + 1);
  }, []);

  const tick = useCallback(async (t: PlanTask, done: boolean) => {
    setTicks((m) => ({ ...m, [t.key]: done }));
    setTickError(null);
    try {
      await api.tickTask(t.key, done);
      if (t.key.startsWith("deadline-")) refetchDeadlines();
    } catch (e) {
      setTicks((m) => ({ ...m, [t.key]: !done }));
      setTickError((e as Error).message);
    }
  }, [refetchDeadlines]);

  const openTask = useCallback((t: PlanTask) => {
    const session = t.session_id ? sessions.find((s) => s.id === t.session_id) : undefined;
    if (session) return setSelected({ session });
    const reading = t.kind === "reading" ? shown?.readings?.find((r) => `reading-${r.section_id ?? 0}` === t.key) : undefined;
    if (reading) setSelected({ reading });
  }, [sessions, shown]);

  if (!saved || !draft || !shown) return <Status error={loadError} loading />;

  function change(next: ScheduleConfig) {
    setDraft(next);
    window.clearTimeout(timer.current);
    if (saved && same(saved.config, next)) {
      setPreview(null);
      setState({ busy: false, error: null });
      return;
    }
    timer.current = window.setTimeout(async () => {
      setState({ busy: true, error: null });
      try {
        setPreview(await api.previewSchedule(next));
        setState({ busy: false, error: null });
      } catch (e) {
        setState({ busy: false, error: (e as Error).message });
      }
    }, PREVIEW_DELAY);
  }

  async function save(): Promise<boolean> {
    if (!draft) return false;
    window.clearTimeout(timer.current);
    setState({ busy: true, error: null });
    try {
      const out = await api.setSchedule(draft);
      setSaved(out);
      setDraft(out.config);
      setPreview(null);
      setTicks({});
      setState({ busy: false, error: null });
      return true;
    } catch (e) {
      setState({ busy: false, error: (e as Error).message });
      return false;
    }
  }

  function discard() {
    window.clearTimeout(timer.current);
    if (saved) setDraft(saved.config);
    setPreview(null);
    setState({ busy: false, error: null });
  }

  function onClick(arg: EventClickArg) {
    const p = arg.event.extendedProps;
    if (!p.deadline && !p.session) return;
    arg.jsEvent.preventDefault();
    const session = p.session as ScheduleSession | undefined;
    if (session) setFocus(session.date);
    setSelected({ deadline: p.deadline as Deadline | undefined, session });
  }

  function onDates(arg: DatesSetArg) {
    store(VIEW_KEY, arg.view.type);
    const { currentStart: start, currentEnd: end } = arg.view;
    const first = isoDay(start);
    const last = isoDay(end);
    range.current = { start: first, end: last };
    const today = saved?.today ?? isoDay(new Date());
    // The focused day stays in the period shown: today when it is in it, else its first day.
    setFocus((f) => (f >= first && f < last ? f : today >= first && today < last ? today : first));
    // Export from the period shown: this week if it includes today, else its first week.
    const now = Date.now();
    setVisible(now >= start.getTime() && now < end.getTime() ? null : first);
  }

  const focusClass = (arg: DayHeaderContentArg | DayCellContentArg) => (isoDay(arg.date) === focus ? ["fc-focused"] : []);
  const status = state.busy ? "Updating…" : state.error ? <Late>{state.error}</Late> : null;
  const focusDay = days.get(focus);
  const sessionTasks = selected?.session
    ? (selected.session.task_keys ?? [])
      .map((k) => days.get(selected.session!.date)?.tasks.find((t) => t.key === k))
      .filter((t): t is PlanTask => !!t)
    : [];

  const dayHead = (
    <>
      <DayHead>
        <IconButton type="button" aria-label="Previous day" onClick={() => setFocus(addDays(focus, -1))}>‹</IconButton>
        <h2>{longDate(focus)}</h2>
        <IconButton type="button" aria-label="Next day" onClick={() => setFocus(addDays(focus, 1))}>›</IconButton>
      </DayHead>
      <DaySub $small>
        {daySummary(focusDay, isDone) || "Nothing planned"}
        {focus !== shown.today && (
          <> · <Button $variant="ghost" $size="sm" onClick={() => setFocus(shown.today)}>Today</Button></>
        )}
      </DaySub>
    </>
  );
  const taskList = (
    <>
      {tickError && <Alert>Could not save the tick: {tickError}</Alert>}
      <DayTasks day={focusDay} sessions={sessions} done={isDone} onTick={tick} onOpen={openTask} timeZone={timeZone} />
    </>
  );

  return (
    <>
      <h1>Calendar</h1>
      <Lead $small>
        When to study each course, and what to get done each day. Change the settings, check the preview, then save:
        your subscribed calendar and the exports follow.
      </Lead>
      <Row>
        <Button $variant="soft" $size="sm" onClick={() => setDialog("settings")}>⚙ Settings</Button>
        <Button $variant="primary" $size="sm" onClick={() => setDialog("subscribe")}>Subscribe</Button>
        <Dropdown text label="Export" trigger="Export ▾" open={exportOpen} onOpenChange={setExportOpen}>
          <MenuItem onClick={() => { setExportOpen(false); setDialog("pdf"); }}>Export as PDF</MenuItem>
          <MenuItem onClick={() => { setExportOpen(false); setDialog("xlsx"); }}>Export as Excel</MenuItem>
          <MenuItem onClick={() => { setExportOpen(false); window.location.href = "/calendar.ics?download=1"; }}>
            Export as ICS
          </MenuItem>
        </Dropdown>
        <Check>
          <input type="checkbox" checked={showBreaks}
            onChange={(e) => { setShowBreaks(e.target.checked); store(BREAKS_KEY, e.target.checked ? "1" : "0"); }} />
          Breaks and days off
        </Check>
        <Muted $small role="status">
          {status ?? (dirty ? "Preview of unsaved changes" : `Plan saved ${savedAt(saved.published_at)}`)}
        </Muted>
      </Row>

      {dirty && (
        <Banner $tone="warning">
          <span>Preview: these changes aren't saved, your subscribed calendar still has the saved plan.</span>
          <Row>
            <Button $variant="ghost" $size="sm" onClick={discard}>Discard</Button>
            <Button $variant="outline" $size="sm" onClick={() => setDialog("settings")}>Edit</Button>
            <Button $variant="primary" $size="sm" onClick={save} disabled={state.busy}>Save</Button>
          </Row>
        </Banner>
      )}
      {error && <Alert>Could not load deadlines: {error}</Alert>}
      {shown.notes.map((n, i) => <Alert key={i} $tone="warning">{n}</Alert>)}
      {!narrow && <Summary data={shown} />}

      {narrow ? (
        <PhoneStack>
          <DayStrip focus={focus} today={shown.today} days={days} onFocus={setFocus} />
          {dayHead}
          <Segmented role="group" aria-label="Show">
            {(["day", "schedule", "tasks"] as PhoneView[]).map((v) => (
              <button key={v} type="button" aria-pressed={phoneView === v}
                onClick={() => { setPhoneView(v); store(PHONE_VIEW_KEY, v); }}>
                {v === "day" ? "Both" : v === "schedule" ? "Schedule" : "Tasks"}
              </button>
            ))}
          </Segmented>
          {phoneView !== "tasks" && (
            <DayTimeline date={focus} sessions={sessions} busy={showBreaks ? shown.busy : []} deadlines={dayDeadlines}
              timeZone={timeZone} onOpen={(s) => setSelected({ session: s })} onDeadline={(d) => setSelected({ deadline: d })} />
          )}
          {phoneView !== "schedule" && <Card aria-label="Tasks of the day">{taskList}</Card>}
          <Summary data={shown} />
        </PhoneStack>
      ) : (
        <Split>
          <CalendarCard data-preview={dirty}>
            <FullCalendar
              ref={ref}
              plugins={[dayGridPlugin, timeGridPlugin]}
              initialView={initialView}
              initialDate={focus}
              headerToolbar={{ left: "prev,next today", center: "title", right: VIEWS.join(",") }}
              buttonText={{ today: "Today", month: "Month", week: "Week", day: "Day" }}
              views={{
                timeGrid: { displayEventTime: false, eventContent: sessionContent },
                dayGrid: { displayEventTime: true },
              }}
              firstDay={1}
              height="auto"
              nowIndicator
              allDaySlot={showBreaks}
              scrollTime={draft.day_start}
              slotMinTime={draft.day_start < "07:00" ? draft.day_start : "07:00"}
              slotMaxTime="24:00"
              dayMaxEventRows={4}
              eventDisplay="block"
              eventTimeFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
              slotLabelFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
              navLinks
              navLinkDayClick={(date) => setFocus(isoDay(date))}
              dayHeaderClassNames={focusClass}
              dayCellClassNames={focusClass}
              events={scheduleEvents}
              eventSources={eventSources}
              eventClick={onClick}
              datesSet={onDates}
            />
          </CalendarCard>
          <Side as="aside" aria-label="Tasks of the focused day">
            {dayHead}
            {taskList}
          </Side>
        </Split>
      )}

      {shown.unscheduled.length > 0 && (
        <DetailsCard>
          <summary>Doesn't fit in {shown.config.days} days ({minutes(shown.unscheduled_minutes)})</summary>
          <List $gap="8px">
            {shown.unscheduled.map((it, i) => <PlanRow key={i} item={it} />)}
          </List>
        </DetailsCard>
      )}

      <Modal open={dialog === "settings"} onClose={closeDialog} label="Schedule settings" wide>
        <DialogHead>
          <h2>Schedule settings</h2>
          <Small $muted>
            Close the dialog to preview your changes in the calendar. Save to update the plan everywhere, your
            subscribed calendar included.
          </Small>
        </DialogHead>
        <ScheduleForm draft={draft} courses={shown.courses} today={saved.today} onChange={change} />
        <SaveBar $tone={dirty ? "warning" : "primary"}>
          <span>{dirty ? "Unsaved changes" : `Saved ${savedAt(saved.published_at)}`}{status && <> · {status}</>}</span>
          <Row>
            {dirty && <Button $variant="ghost" $size="sm" onClick={discard}>Discard</Button>}
            {dirty && <Button $variant="outline" $size="sm" onClick={closeDialog}>Preview</Button>}
            <Button $variant={dirty ? "primary" : "soft"} $size="sm" disabled={state.busy}
              onClick={async () => { if (await save()) closeDialog(); }}>
              {dirty ? "Save" : "Re-plan now"}
            </Button>
            {!dirty && <Button $variant="ghost" $size="sm" onClick={closeDialog}>Close</Button>}
          </Row>
        </SaveBar>
      </Modal>

      <ReminderSettings />

      <EventDialog selected={selected} site={saved.site_url ?? ""} timeZone={timeZone} onClose={close}
        tasks={sessionTasks} done={isDone} onTick={tick}
        onDeadline={(d) => {
          setSelected({ deadline: d });
          refetchDeadlines();
        }} />
      <Modal open={dialog === "subscribe"} onClose={closeDialog} label="Subscribe to your study calendar">
        <h2 style={{ margin: 0 }}>Subscribe</h2>
        <CalendarFeed />
        <Button $variant="ghost" $block onClick={closeDialog}>Close</Button>
      </Modal>
      {(dialog === "pdf" || dialog === "xlsx") && (
        <ExportWeeks format={dialog} open onClose={closeDialog} start={visible ?? saved.today} />
      )}
    </>
  );
}
