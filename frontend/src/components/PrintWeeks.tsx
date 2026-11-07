import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import styled, { createGlobalStyle } from "styled-components";
import { api, type Deadline, type Schedule } from "../api";
import { minutes } from "../pages/Plan";
import { clock } from "./ScheduleBlock";
import { Alert, Button, Check, Field, FieldRow, Input, Modal, Select, Small, Toggles } from "../ui";

// Print one or more weeks of the calendar as a plain table: the browser's print dialog
// saves it as a PDF ("Save as PDF" / "Print to PDF"), on a computer or a phone, with no PDF
// library. The table is rendered in its own element next to the app and only shows when
// printing; while this dialog is open, printing hides everything else.

const PrintOnly = createGlobalStyle`
  @media print {
    @page { margin: 14mm 12mm; }
    html, body { background: #fff !important; color: #000 !important; }
    body > :not(#print-weeks) { display: none !important; }
  }
`;

const Sheet = styled.div`
  display: none;
  @media print {
    display: block;
    color: #000;
    font: 10.5pt/1.35 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  section { break-after: page; }
  section:last-child { break-after: auto; }
  h1 { font-size: 15pt; margin: 0 0 2pt; }
  p { margin: 0 0 8pt; color: #444; font-size: 9pt; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; vertical-align: top; padding: 3pt 6pt; border-bottom: .5pt solid #bbb; }
  thead th { font-size: 9pt; color: #444; border-bottom: 1pt solid #000; }
  tr { break-inside: avoid; }
  tr.day th { padding-top: 9pt; font-size: 11pt; border-bottom: 1pt solid #000; }
  tr.day th span { float: right; font-weight: 400; font-size: 9pt; color: #444; }
  td.time { width: 82pt; white-space: nowrap; font-variant-numeric: tabular-nums; }
  td.course { width: 90pt; }
  tr.busy td { color: #555; font-style: italic; }
  tr.due td { font-weight: 700; }
  tr.free td { color: #777; }
  small { display: block; color: #444; font-weight: 400; font-style: normal; }
`;

type Row = {
  key: string;
  start: number | null; // null: all day
  end?: number;
  kind: "block" | "due" | "busy";
  what: string;
  sub?: string;
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
          sub: b.label, course: b.course_short || b.course_name,
        });
      }
    }
    if (withBusy) {
      for (const u of data.busy) {
        add(u.date, { key: `u${u.date}${u.start}`, start: u.all_day ? null : u.start, end: u.end, kind: "busy",
          what: u.reason || "Unavailable", sub: "No study", course: "", minutes: 0 });
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
      <Modal open={open} onClose={onClose} label="Print or save as PDF">
        <h2 style={{ margin: 0 }}>Print or save as PDF</h2>
        <Small $muted>
          A simple table per week. In the print dialog, pick “Save as PDF” to get a file.
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
            {weekStarts.map((monday) => (
              <section key={monday}>
                <h1>Study plan · week of {dayTitle(monday, { day: "numeric", month: "long", year: "numeric" })}</h1>
                <p>
                  {dayTitle(monday, { weekday: "short", day: "numeric", month: "short" })} – {dayTitle(addDays(monday, 6), { weekday: "short", day: "numeric", month: "short" })}
                  {data.published_at && ` · plan saved ${new Date(data.published_at * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`}
                  {tz && ` · times in ${tz}`}
                </p>
                <table>
                  <thead>
                    <tr><th>Time</th><th>What</th><th>Course</th></tr>
                  </thead>
                  <tbody>
                    {Array.from({ length: 7 }, (_, i) => addDays(monday, i)).map((day) => {
                      const rows = byDay.get(day) ?? [];
                      const total = rows.reduce((n, r) => n + r.minutes, 0);
                      return [
                        <tr className="day" key={day}>
                          <th colSpan={3}>{dayTitle(day)}{total > 0 && <span>{minutes(total)} of study</span>}</th>
                        </tr>,
                        ...(rows.length ? rows.map((r) => (
                          <tr key={r.key} className={r.kind === "block" ? "" : r.kind}>
                            <td className="time">
                              {r.start === null ? "All day" : r.end && r.end !== r.start
                                ? `${clock(r.start, tz)}–${clock(r.end, tz)}` : clock(r.start, tz)}
                            </td>
                            <td>{r.what}{r.sub && <small>{r.sub}</small>}</td>
                            <td className="course">{r.course}</td>
                          </tr>
                        )) : [<tr className="free" key={`${day}-free`}><td className="time">—</td><td colSpan={2}>Nothing planned</td></tr>]),
                      ];
                    })}
                  </tbody>
                </table>
              </section>
            ))}
          </Sheet>
        </>,
        host,
      )}
    </>
  );
}
