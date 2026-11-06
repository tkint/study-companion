import { useMemo, useRef, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import listPlugin from "@fullcalendar/list";
import type { EventClickArg, EventInput, EventSourceFuncArg } from "@fullcalendar/core";
import { api, type Deadline, type Feed } from "../api";
import { DeadlineItem } from "../components/DeadlineList";
import { ReminderSettings } from "../components/Reminders";
import { courseColor } from "../format";

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

  function onClick(arg: EventClickArg) {
    arg.jsEvent.preventDefault();
    setSelected(arg.event.extendedProps.deadline as Deadline);
  }

  return (
    <>
      <h1>Calendar</h1>
      {error && <p className="alert alert-error">Could not load deadlines: {error}</p>}
      <div className="calendar">
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
      </div>
      {selected && (
        <div className="sheet-backdrop" onClick={() => setSelected(null)}>
          <div className="sheet" role="dialog" aria-modal="true" aria-label="Deadline" onClick={(e) => e.stopPropagation()}>
            <ul className="deadlines">
              <DeadlineItem
                d={selected}
                onChange={(d) => {
                  setSelected(d);
                  ref.current?.getApi().refetchEvents();
                }}
              />
            </ul>
            <button className="btn btn-ghost btn-block" onClick={() => setSelected(null)}>
              Close
            </button>
          </div>
        </div>
      )}
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
    <section className="subscribe">
      <h2>Add to your phone or Outlook calendar</h2>
      <p className="muted">
        Subscribe once and new deadlines, alarms and daily study reminders appear in your
        calendar app after each sync. The link is private: anyone who has it can see your deadlines.
      </p>
      {!feed ? (
        <div className="row">
          <button className="btn btn-primary" onClick={show}>Show subscription link</button>
          <a className="btn btn-ghost" href="/calendar.ics?download=1">Download .ics</a>
        </div>
      ) : (
        <>
          <input className="feed-url" readOnly value={feed.url} onFocus={(e) => e.currentTarget.select()} aria-label="Calendar link" />
          <div className="row">
            <a className="btn btn-primary" href={feed.webcal}>Subscribe on this device</a>
            <button className="btn btn-ghost" onClick={copy}>{copied ? "Copied" : "Copy link"}</button>
            <button className="btn btn-ghost" onClick={rotate}>New link</button>
          </div>
          <p className="muted small">
            iPhone: tap Subscribe. Google Calendar: Settings → Add calendar → From URL, paste the
            link. Outlook: Add calendar → Subscribe from web.
          </p>
        </>
      )}
      {error && <p className="alert alert-error">{error}</p>}
    </section>
  );
}
