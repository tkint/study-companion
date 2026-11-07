import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import styled from "styled-components";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import listPlugin from "@fullcalendar/list";
import type { DatesSetArg, EventClickArg, EventInput, EventSourceFuncArg } from "@fullcalendar/core";
import { api, type Deadline, type Schedule, type ScheduleBlock, type ScheduleConfig } from "../api";
import { Status } from "../components/common";
import { CalendarFeed } from "../components/CalendarFeed";
import { DeadlineItem } from "../components/DeadlineList";
import { PrintWeeks } from "../components/PrintWeeks";
import { ReminderSettings } from "../components/Reminders";
import { BlockRow, Summary } from "../components/ScheduleBlock";
import { ScheduleForm } from "../components/ScheduleForm";
import { courseColor } from "../format";
import { DayHead, minutes, PlanRow } from "./Plan";
import { Alert, Banner, Button, DetailsCard, Late, Lead, List, Modal, Muted, Row, Small } from "../ui";

// One calendar for everything (issue: unified study calendar): the published study schedule
// (app/planner/published.py), Moodle deadlines and your unavailabilities, in FullCalendar.
// The schedule settings are a form: changes show at once as a preview in the calendar, and
// Save publishes them, which is what the subscribed feed (/calendar.ics) and the printed
// weeks show. Subscribe, download the .ics or print weeks as a table (PDF) from the toolbar.

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
  --fc-today-bg-color: ${({ theme }) => theme.colors.primarySoft};
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
  .fc-recall, .fc-flashcards { opacity: .85; }
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

const narrow = () => window.matchMedia("(max-width: 640px)").matches;
const PREVIEW_DELAY = 600;

function blockEvent(b: ScheduleBlock): EventInput {
  const course = b.course_short || b.course_name;
  return {
    id: `b${b.start}`,
    title: `${course ? course + ": " : ""}${b.title}${b.parts > 1 ? ` (${b.part}/${b.parts})` : ""}`,
    start: new Date(b.start * 1000),
    end: new Date(b.end * 1000),
    color: b.course_id ? courseColor(b.course_id) : "var(--c-primary)",
    classNames: ["fc-study", `fc-${b.kind}`, ...(b.late ? ["fc-late"] : []), ...(b.end * 1000 < Date.now() ? ["fc-done"] : [])],
    extendedProps: { block: b },
  };
}

function deadlineEvent(d: Deadline): EventInput {
  return {
    id: `d${d.id}`,
    title: `📌 ${d.course_shortname ? d.course_shortname + ": " : ""}${d.name}`,
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

export default function Calendar() {
  const ref = useRef<FullCalendar>(null);
  const [saved, setSaved] = useState<Schedule | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draft, setDraft] = useState<ScheduleConfig | null>(null);
  const [preview, setPreview] = useState<Schedule | null>(null);
  const [state, setState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
  const [selected, setSelected] = useState<{ deadline?: Deadline; block?: ScheduleBlock } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"settings" | "subscribe" | "print" | null>(null);
  const [visible, setVisible] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const initialView = useMemo(() => (narrow() ? "listWeek" : "nextDays"), []);

  useEffect(() => {
    api.schedule()
      .then((s) => {
        setSaved(s);
        setDraft(s.config);
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

  const scheduleEvents = useMemo<EventInput[]>(() => {
    if (!shown) return [];
    const blocks = shown.days.flatMap((d) => d.blocks).map(blockEvent);
    const busy = shown.busy.map((u) => ({
      id: `u${u.start}`,
      title: u.reason || "Unavailable",
      start: u.all_day ? u.date : new Date(u.start * 1000),
      end: u.all_day ? undefined : new Date(u.end * 1000),
      allDay: u.all_day,
      display: "background",
    }));
    return [...blocks, ...busy];
  }, [shown]);

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
    if (!p.deadline && !p.block) return;
    arg.jsEvent.preventDefault();
    setSelected({ deadline: p.deadline as Deadline | undefined, block: p.block as ScheduleBlock | undefined });
  }

  function onDates(arg: DatesSetArg) {
    // Print from the period shown: this week if it includes today, else its first week.
    const { currentStart: start, currentEnd: end } = arg.view;
    const now = Date.now();
    const iso = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}-${String(start.getDate()).padStart(2, "0")}`;
    setVisible(now >= start.getTime() && now < end.getTime() ? null : iso);
  }

  const status = state.busy ? "Updating…" : state.error ? <Late>{state.error}</Late> : null;

  return (
    <>
      <h1>Calendar</h1>
      <Lead $small>
        Your study plan with times, your deadlines and the times you can't study, in one calendar. Change the settings,
        check the preview, then save: your subscribed calendar follows.
      </Lead>
      <Row>
        <Button $variant="soft" $size="sm" onClick={() => setDialog("settings")}>⚙ Settings</Button>
        <Button $variant="primary" $size="sm" onClick={() => setDialog("subscribe")}>Subscribe</Button>
        <Button as="a" $variant="outline" $size="sm" href="/calendar.ics?download=1" download>Download .ics</Button>
        <Button $variant="outline" $size="sm" onClick={() => setDialog("print")}>Print or PDF</Button>
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
      <Summary data={shown} />

      <CalendarCard data-preview={dirty}>
        <FullCalendar
          ref={ref}
          plugins={[dayGridPlugin, timeGridPlugin, listPlugin]}
          initialView={initialView}
          headerToolbar={{
            left: "prev,next today",
            center: "title",
            right: narrow() ? "listWeek,timeGridDay,dayGridMonth" : "nextDays,timeGridWeek,dayGridMonth,listWeek",
          }}
          buttonText={{ today: "Today", month: "Month", week: "Week", day: "Day", list: "List" }}
          views={{
            // From today: the days ahead, not the half-past week.
            nextDays: { type: "timeGrid", duration: { days: 7 }, dateIncrement: { days: 7 }, buttonText: "7 days" },
            dayGridMonth: { displayEventTime: !narrow() },
            listWeek: { buttonText: "List" },
          }}
          firstDay={1}
          height="auto"
          nowIndicator
          allDaySlot
          scrollTime={draft.day_start}
          slotMinTime={draft.day_start < "07:00" ? draft.day_start : "07:00"}
          slotMaxTime="24:00"
          dayMaxEventRows={4}
          eventDisplay="block"
          eventTimeFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
          slotLabelFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
          noEventsContent="Nothing planned in this period."
          events={scheduleEvents}
          eventSources={eventSources}
          eventClick={onClick}
          datesSet={onDates}
        />
      </CalendarCard>

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

      <Modal open={!!selected} onClose={close} label={selected?.block ? "Study block" : "Deadline"}>
        {selected?.deadline && (
          <List $animate={false}>
            <DeadlineItem
              d={selected.deadline}
              onChange={(d) => {
                setSelected({ deadline: d });
                ref.current?.getApi().getEventSourceById("deadlines")?.refetch();
              }}
            />
          </List>
        )}
        {selected?.block && (
          <>
            <DayHead as="h3">
              <span>{new Date(selected.block.start * 1000).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</span>
            </DayHead>
            <List $animate={false}><BlockRow block={selected.block} timeZone={shown.timezone} /></List>
          </>
        )}
        <Button $variant="ghost" $block onClick={close}>Close</Button>
      </Modal>
      <Modal open={dialog === "subscribe"} onClose={closeDialog} label="Subscribe to your study calendar">
        <h2 style={{ margin: 0 }}>Subscribe</h2>
        <CalendarFeed />
        <Button $variant="ghost" $block onClick={closeDialog}>Close</Button>
      </Modal>
      <PrintWeeks open={dialog === "print"} onClose={closeDialog} data={saved} start={visible ?? saved.today} />
    </>
  );
}
