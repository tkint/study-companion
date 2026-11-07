import { useEffect, useState } from "react";
import { Button, Check, Field, FieldRow, Input, Modal, Row, Select, Small, Toggles } from "../ui";

// Export the saved schedule as a PDF: one A4 landscape page per week, like a printed
// timetable (built by the server, app/planner/print_week.py). Open shows it in a new tab;
// Download saves the file. Nothing is printed unless you print it yourself.

function addDays(iso: string, n: number): string {
  return new Date(Date.parse(`${iso}T12:00:00Z`) + n * 86400000).toISOString().slice(0, 10);
}

/** The Monday of the week of ``iso`` (YYYY-MM-DD). */
export function mondayOf(iso: string): string {
  const day = new Date(`${iso}T12:00:00Z`).getUTCDay(); // 0 Sunday
  return addDays(iso, -((day + 6) % 7));
}

function short(iso: string, year = false): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString(undefined, {
    day: "numeric", month: "short", ...(year ? { year: "numeric" } : {}), timeZone: "UTC",
  });
}

export function ExportPdf({ open, onClose, start }: {
  open: boolean;
  onClose: () => void;
  /** A date in the first week to export (the week shown in the calendar). */
  start: string;
}) {
  const [first, setFirst] = useState(() => mondayOf(start));
  const [weeks, setWeeks] = useState(1);
  const [withDeadlines, setWithDeadlines] = useState(true);
  const [withBusy, setWithBusy] = useState(true);

  useEffect(() => {
    if (open) setFirst(mondayOf(start));
  }, [open, start]);

  const q = new URLSearchParams({ from: first, weeks: String(weeks) });
  if (!withDeadlines) q.set("deadlines", "0");
  if (!withBusy) q.set("busy", "0");
  const url = `/api/schedule.pdf?${q}`;

  return (
    <Modal open={open} onClose={onClose} label="Export as PDF">
      <h2 style={{ margin: 0 }}>Export as PDF</h2>
      <Small $muted>One page per week: a column per day, your study blocks at their times.</Small>
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
      <Small $muted role="status">
        {short(first)} – {short(addDays(first, weeks * 7 - 1), true)}
      </Small>
      <Row>
        <Button as="a" $variant="primary" href={url} target="_blank" rel="noopener" onClick={onClose}>Open PDF</Button>
        <Button as="a" $variant="outline" href={url} download={`study-plan-${first}.pdf`} onClick={onClose}>Download</Button>
        <Button $variant="ghost" onClick={onClose}>Close</Button>
      </Row>
    </Modal>
  );
}
