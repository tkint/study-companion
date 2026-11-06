import { useCallback, useMemo, useRef, useState } from "react";
import styled from "styled-components";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import listPlugin from "@fullcalendar/list";
import type { EventClickArg, EventInput, EventSourceFuncArg } from "@fullcalendar/core";
import { api, type Deadline, type Feed } from "../api";
import { DeadlineItem } from "../components/DeadlineList";
import { ReminderSettings, SettingsSection } from "../components/Reminders";
import { courseColor } from "../format";
import { Alert, Button, Input, Lead, List, Modal, Row, Small } from "../ui";

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
  .fc-done { opacity: .5; text-decoration: line-through; }
  .fc-overdue .fc-event-title, .fc-overdue .fc-list-event-title { font-weight: 700; }
  ${({ theme }) => theme.media.phone} {
    padding: 6px;
    .fc .fc-header-toolbar { flex-wrap: wrap; justify-content: space-between; }
    .fc .fc-toolbar-chunk:nth-child(2) { order: -1; width: 100%; text-align: center; }
    .fc .fc-toolbar-chunk { display: flex; gap: 4px; }
    .fc .fc-button { padding: .4em .6em; }
  }
`;

const FeedUrl = styled(Input)`
  font-size: ${({ theme }) => theme.fontSizes.sm};
  background: ${({ theme }) => theme.colors.surfaceSunken};
`;

const narrow = () => window.matchMedia("(max-width: 640px)").matches;

function toEvent(d: Deadline): EventInput {
  return {
    id: String(d.id),
    title: `${d.course_shortname ? d.course_shortname + ": " : ""}${d.name}`,
    start: new Date(d.due_at * 1000),
    allDay: false,
    color: courseColor(d.course_id),
    classNames: d.done ? ["fc-done"] : d.due_at * 1000 < Date.now() ? ["fc-overdue"] : [],
    extendedProps: { deadline: d },
  };
}

export default function Calendar() {
  const ref = useRef<FullCalendar>(null);
  const [selected, setSelected] = useState<Deadline | null>(null);
  const [error, setError] = useState<string | null>(null);
  const initialView = useMemo(() => (narrow() ? "listMonth" : "dayGridMonth"), []);

  async function events(info: EventSourceFuncArg) {
    try {
      const from = Math.floor(info.start.getTime() / 1000);
      const to = Math.ceil(info.end.getTime() / 1000);
      const items = await api.deadlines(from, to);
      setError(null);
      return items.map(toEvent);
    } catch (e) {
      setError((e as Error).message);
      return [];
    }
  }

  const close = useCallback(() => setSelected(null), []);

  function onClick(arg: EventClickArg) {
    arg.jsEvent.preventDefault();
    setSelected(arg.event.extendedProps.deadline as Deadline);
  }

  return (
    <>
      <h1>Calendar</h1>
      {error && <Alert>Could not load deadlines: {error}</Alert>}
      <CalendarCard>
        <FullCalendar
          ref={ref}
          plugins={[dayGridPlugin, timeGridPlugin, listPlugin]}
          initialView={initialView}
          headerToolbar={{ left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek,listMonth" }}
          buttonText={{ today: "Today", month: "Month", week: "Week", list: "List" }}
          firstDay={1}
          height="auto"
          nowIndicator
          dayMaxEventRows={3}
          eventDisplay="block"
          views={{ dayGridMonth: { displayEventTime: !narrow() } }}
          eventTimeFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
          noEventsContent="No deadlines in this period."
          events={events}
          eventClick={onClick}
        />
      </CalendarCard>
      <Modal open={!!selected} onClose={close} label="Deadline">
        {selected && (
          <List $animate={false}>
            <DeadlineItem
              d={selected}
              onChange={(d) => {
                setSelected(d);
                ref.current?.getApi().refetchEvents();
              }}
            />
          </List>
        )}
        <Button $variant="ghost" $block onClick={close}>
          Close
        </Button>
      </Modal>
      <ReminderSettings />
      <Subscribe />
    </>
  );
}

function Subscribe() {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function show() {
    try {
      setFeed(await api.feed());
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function rotate() {
    if (!window.confirm("Make a new link? Calendars subscribed with the old link stop updating.")) return;
    setFeed(await api.newFeed());
    setCopied(false);
  }

  async function copy() {
    if (!feed) return;
    try {
      await navigator.clipboard.writeText(feed.url);
      setCopied(true);
    } catch {
      window.prompt("Copy this link", feed.url);
    }
  }

  return (
    <SettingsSection>
      <h2>Add to your phone or Outlook calendar</h2>
      <Lead>
        Subscribe once and new deadlines, alarms and daily study reminders appear in your
        calendar app after each sync. The link is private: anyone who has it can see your deadlines.
      </Lead>
      {!feed ? (
        <Row>
          <Button $variant="primary" onClick={show}>Show subscription link</Button>
          <Button as="a" $variant="outline" href="/calendar.ics?download=1">Download .ics</Button>
        </Row>
      ) : (
        <>
          <FeedUrl readOnly value={feed.url} onFocus={(e) => e.currentTarget.select()} aria-label="Calendar link" />
          <Row>
            <Button as="a" $variant="primary" href={feed.webcal}>Subscribe on this device</Button>
            <Button $variant="outline" onClick={copy}>{copied ? "Copied ✓" : "Copy link"}</Button>
            <Button $variant="ghost" onClick={rotate}>New link</Button>
          </Row>
          <Small $muted>
            iPhone: tap Subscribe. Google Calendar: Settings → Add calendar → From URL, paste the
            link. Outlook: Add calendar → Subscribe from web.
          </Small>
        </>
      )}
      {error && <Alert>{error}</Alert>}
    </SettingsSection>
  );
}
