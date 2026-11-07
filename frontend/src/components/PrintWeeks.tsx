import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import styled, { createGlobalStyle } from "styled-components";
import { api, type Deadline, type Schedule } from "../api";
import { clock } from "./ScheduleBlock";
import { Alert, Button, Check, Field, FieldRow, Input, Modal, Select, Small, Toggles } from "../ui";

// Print one or more weeks of the calendar, one page each: a time grid with a column per day
// and the study blocks at their times (like a printed timetable). The browser's print dialog
// saves it as a PDF ("Save as PDF" / "Print to PDF"), on a computer or a phone, with no PDF
// library. The table is rendered in its own element next to the app and only shows when
// printing; while this dialog is open, printing hides everything else.

const PrintOnly = createGlobalStyle`
  @media print {
    @page { size: A4 landscape; margin: 12mm 10mm; }
    html, body { background: #fff !important; color: #000 !important; }
    body > :not(#print-weeks) { display: none !important; }
  }
`;

const Sheet = styled.div`
  display: none;
  @media print {
    display: block;
    color: #000;
    font: 9pt/1.25 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  section {
    position: relative;
    height: 182mm; /* A4 landscape minus the page margins */
    display: flex;
    flex-direction: column;
    break-after: page;
  }
  section:last-child { break-after: auto; }
  header { margin: 0 0 3mm; }
  header strong { display: block; font-size: 13pt; }
  header span { font-size: 11pt; }
  footer { margin-top: auto; padding-top: 3mm; font: 9pt Georgia, "Times New Roman", serif; }
  .grid { display: grid; border: .6pt solid #000; }
  .head { display: contents; }
  .head > div { border-left: .6pt solid #000; border-bottom: .6pt solid #000; text-align: center;
    font-weight: 700; font-size: 11pt; padding: 1mm 0; }
  .head > div:first-child { border-left: 0; }
  .hours { position: relative; background: #f2f2f2; }
  .hours div { position: absolute; left: 1.2mm; font-size: 7.5pt; color: #333; transform: translateY(1px); }
  .col { position: relative; border-left: .6pt solid #000; }
  .line { position: absolute; left: 0; right: 0; border-top: .3pt solid #c8c8c8; }
  .ev { position: absolute; left: 1mm; right: 1mm; overflow: hidden; padding: .6mm 1mm;
    border: .6pt solid #333; background: #4fa6d6; font-size: 8pt; line-height: 1.2; }
  .ev b { font-weight: 700; }
  .ev.short { padding: 0 1mm; white-space: nowrap; text-overflow: ellipsis; font-size: 7pt; line-height: 1.1; }
  .ev.short small { display: none; }
  .ev small { display: block; font-size: 7.5pt; }
  .ev.recall, .ev.flashcards { background: #cfdfe9; }
  .ev.busy { background: repeating-linear-gradient(135deg, #e6e6e6 0 4px, #f6f6f6 4px 8px); border-color: #999;
    color: #444; font-style: italic; }
  .ev.due { left: auto; width: 46%; background: #fff; border: 1pt dashed #000; font-weight: 700; z-index: 1; }
  .allday { position: absolute; top: 0; bottom: 0; left: 0; right: 0;
    background: repeating-linear-gradient(135deg, #ececec 0 4px, #fafafa 4px 8px); }
  .allday span { display: block; padding: 1mm; font-style: italic; color: #444; }
`;

type Row = {
  key: string;
  start: number | null; // null: all day
  end?: number;
  kind: "block" | "due" | "busy";
  what: string;
  /** Block kind (deep, practice, recall, flashcards), for its colour. */
  sub?: string;
  label?: string;
  course: string;
  minutes: number;
};

const DAY = 86400000;

function addDays(iso: string, n: number): string {
  return new Date(Date.parse(`${iso}T12:00:00Z`) + n * DAY).toISOString().slice(0, 10);
}

/** The Monday of the week of ``iso`` (YYYY-MM-DD). */
export function mondayOf(iso: string): string {
  const day = new Date(`${iso}T12:00:00Z`).getUTCDay(); // 0 Sunday
  return addDays(iso, -((day + 6) % 7));
}

function localDate(ts: number, timeZone: string): string {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" })
      .format(new Date(ts * 1000));
  } catch {
    return new Date(ts * 1000).toISOString().slice(0, 10);
  }
}

/** Minutes since local midnight of ``ts`` in ``timeZone``. */
function localMinutes(ts: number, timeZone: string): number {
  try {
    const parts = new Intl.DateTimeFormat("en-GB", { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(new Date(ts * 1000));
    const n = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? 0);
    return n("hour") * 60 + n("minute");
  } catch {
    const d = new Date(ts * 1000);
    return d.getHours() * 60 + d.getMinutes();
  }
}

function hhmm(m: number): string {
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

const toMinutes = (t: string) => (t === "24:00" ? 1440 : Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5)));

function dayTitle(iso: string, opts: Intl.DateTimeFormatOptions = { weekday: "long", day: "numeric", month: "long" }) {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString(undefined, { ...opts, timeZone: "UTC" });
}

export function PrintWeeks({ open, onClose, data, start }: {
  open: boolean;
  onClose: () => void;
  data: Schedule;
  /** A date in the first week to print (the week shown in the calendar). */
  start: string;
}) {
  const [first, setFirst] = useState(() => mondayOf(start));
  const [weeks, setWeeks] = useState(1);
  const [withDeadlines, setWithDeadlines] = useState(true);
  const [withBusy, setWithBusy] = useState(true);
  const [deadlines, setDeadlines] = useState<Deadline[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const tz = data.timezone;

  useEffect(() => {
    if (!open) return;
    const el = document.createElement("div");
    el.id = "print-weeks";
    document.body.appendChild(el);
    setHost(el);
    return () => {
      el.remove();
      setHost(null);
    };
  }, [open]);
  const last = addDays(first, weeks * 7 - 1);

  useEffect(() => {
    if (open) setFirst(mondayOf(start));
  }, [open, start]);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setDeadlines(null);
    const from = Date.parse(`${first}T00:00:00Z`) / 1000 - 86400;
    const to = Date.parse(`${last}T00:00:00Z`) / 1000 + 2 * 86400;
    api.deadlines(from, to)
      .then((d) => live && (setDeadlines(d), setError(null)))
      .catch((e: Error) => live && (setDeadlines([]), setError(e.message)));
    return () => {
      live = false;
    };
  }, [open, first, last]);

  const byDay = useMemo(() => {
    const out = new Map<string, Row[]>();
    const add = (date: string, row: Row) => {
      if (date < first || date > last) return;
      out.set(date, [...(out.get(date) ?? []), row]);
    };
    for (const d of data.days) {
      for (const [i, b] of d.blocks.entries()) {
        add(d.date, {
          key: `b${d.date}${i}`, start: b.start, end: b.end, kind: "block", minutes: b.minutes,
          what: b.title + (b.parts > 1 ? ` (${b.kind === "recall" ? "review" : "part"} ${b.part}/${b.parts})` : ""),
          sub: b.kind, label: b.label, course: b.course_short || b.course_name,
        });
      }
    }
    if (withBusy) {
      for (const u of data.busy) {
        add(u.date, { key: `u${u.date}${u.start}`, start: u.all_day ? null : u.start, end: u.end, kind: "busy",
          what: u.reason || "Unavailable", course: "", minutes: 0 });
      }
    }
    if (withDeadlines) {
      for (const d of deadlines ?? []) {
        add(localDate(d.due_at, tz), { key: `d${d.id}`, start: d.due_at, kind: "due", minutes: 0,
          what: `Due: ${d.name}${d.done ? " ✓" : ""}`, course: d.course_shortname ?? "" });
      }
    }
    for (const rows of out.values()) rows.sort((a, b) => (a.start ?? 0) - (b.start ?? 0));
    return out;
  }, [data, deadlines, withBusy, withDeadlines, first, last, tz]);

  const weekStarts = Array.from({ length: weeks }, (_, i) => addDays(first, i * 7));
  const count = [...byDay.values()].reduce((n, rows) => n + rows.length, 0);

  return (
    <>
      <Modal open={open} onClose={onClose} label="Export as PDF">
        <h2 style={{ margin: 0 }}>Export as PDF</h2>
        <Small $muted>
          One page per week: a column per day, your study blocks at their times. In the print dialog, pick
          “Save as PDF” to get a file.
        </Small>
        <FieldRow>
          <Field>Week of
            <Input type="date" value={first} onChange={(e) => e.target.value && setFirst(mondayOf(e.target.value))} />
          </Field>
          <Field>Weeks
            <Select value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
              {[1, 2, 3, 4, 6, 8].map((n) => <option key={n} value={n}>{n}</option>)}
            </Select>
          </Field>
        </FieldRow>
        <Toggles>
          <Check><input type="checkbox" checked={withDeadlines} onChange={(e) => setWithDeadlines(e.target.checked)} />
            Deadlines</Check>
          <Check><input type="checkbox" checked={withBusy} onChange={(e) => setWithBusy(e.target.checked)} />
            When I can't study</Check>
        </Toggles>
        {error && <Alert>Could not load deadlines: {error}</Alert>}
        <Small $muted role="status">
          {dayTitle(first, { day: "numeric", month: "short" })} – {dayTitle(last, { day: "numeric", month: "short", year: "numeric" })}
          {" · "}{deadlines === null ? "loading…" : `${count} entr${count === 1 ? "y" : "ies"}`}
        </Small>
        <Button $variant="primary" $block disabled={deadlines === null} onClick={() => window.print()}>
          Print or save as PDF
        </Button>
        <Button $variant="ghost" $block onClick={onClose}>Close</Button>
      </Modal>
      {host && createPortal(
        <>
          <PrintOnly />
          <Sheet aria-hidden="true">
            {weekStarts.map((monday) => {
              // Monday to Friday, plus the weekend days that have something on them.
              const days = Array.from({ length: 7 }, (_, i) => addDays(monday, i))
                .filter((d, i) => i < 5 || (byDay.get(d) ?? []).length > 0);
              // Deadlines don't stretch the grid (a 23:59 or 02:00 deadline sits at its edge).
              const rows = days.flatMap((d) => byDay.get(d) ?? []).filter((r) => r.start !== null && r.kind !== "due");
              let from = Math.min(toMinutes(data.config.day_start), ...rows.map((r) => localMinutes(r.start!, tz)));
              let to = Math.max(toMinutes(data.config.day_end),
                ...rows.map((r) => (r.end && r.end > r.start! ? localMinutes(r.end, tz) || 1440 : localMinutes(r.start!, tz) + 30)));
              from = Math.max(0, Math.floor(from / 30) * 30);
              to = Math.min(1440, Math.ceil(to / 30) * 30);
              const span = Math.max(60, to - from);
              const pos = (m: number) => `${((m - from) / span) * 100}%`;
              const slots = Array.from({ length: span / 30 }, (_, i) => from + i * 30);
              return (
                <section key={monday}>
                  <header>
                    <strong>{data.owner || "Study plan"}</strong>
                    <span>
                      Week of {dayTitle(monday, { weekday: "long", day: "numeric", month: "long", year: "numeric" })} to{" "}
                      {dayTitle(days[days.length - 1], { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
                    </span>
                  </header>
                  <div className="grid" style={{ gridTemplateColumns: `14mm repeat(${days.length}, 1fr)`, gridTemplateRows: "auto 1fr", flex: 1 }}>
                    <div className="head">
                      <div />
                      {days.map((d) => <div key={d}>{dayTitle(d, { weekday: "long", day: "numeric" })}</div>)}
                    </div>
                    <div className="hours">
                      {slots.map((m) => <div key={m} style={{ top: pos(m) }}>{hhmm(m)}</div>)}
                    </div>
                    {days.map((d) => (
                      <div className="col" key={d}>
                        {slots.slice(1).map((m) => <div key={m} className="line" style={{ top: pos(m) }} />)}
                        {(byDay.get(d) ?? []).map((r) => {
                          if (r.start === null) {
                            return <div key={r.key} className="allday"><span>{r.what}</span></div>;
                          }
                          const due = r.kind === "due";
                          const s0 = due ? Math.min(Math.max(from, localMinutes(r.start, tz)), to - 20)
                            : Math.max(from, localMinutes(r.start, tz));
                          const e0 = r.end && r.end > r.start ? (localMinutes(r.end, tz) || 1440) : s0 + 20;
                          const time = r.end && r.end > r.start
                            ? `${clock(r.start, tz)}–${clock(r.end, tz)}` : clock(r.start, tz);
                          return (
                            <div key={r.key} className={`ev ${r.kind === "block" ? r.sub ?? "" : r.kind}${e0 - s0 < 30 ? " short" : ""}`}
                              style={{ top: pos(s0), height: `calc(${((Math.min(e0, to) - s0) / span) * 100}% - 1px)` }}>
                              <b>{time}</b> {r.what}
                              {(r.course || r.label) && <small>{[r.course, r.label].filter(Boolean).join(" · ")}</small>}
                            </div>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                  <footer>Printed on {new Date().toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}</footer>
                </section>
              );
            })}
          </Sheet>
        </>,
        host,
      )}
    </>
  );
}
