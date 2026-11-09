import { useEffect, useState } from "react";
import { Button, Check, Field, FieldRow, Input, Modal, Row, Select, Small, Toggles } from "../ui";

// Export weeks of the saved schedule, built by the server:
// - PDF: the calendar (one A4 landscape page per week), then one portrait page of tasks per
//   day (app/planner/print_week.py). Open shows it in a new tab; Download saves the file.
// - Excel: the same as sheets: a calendar sheet, then one task sheet per day
//   (app/planner/sheet_week.py). Download only (a browser can't show it).

export type WeeksFormat = "pdf" | "xlsx";

const FORMATS = {
  pdf: { name: "PDF", what: "The calendar (a page per week), then a page of tasks for each day, with checkboxes." },
  xlsx: {
    name: "Excel",
    what: "A calendar sheet, then a sheet of tasks for each day, with a Done column. Prints cleanly.",
  },
} as const;

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

export function ExportWeeks({ format, open, onClose, start }: {
  format: WeeksFormat;
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
  const url = `/api/schedule.${format}?${q}`;
  const { name, what } = FORMATS[format];

  return (
    <Modal open={open} onClose={onClose} label={`Export as ${name}`}>
      <h2 style={{ margin: 0 }}>Export as {name}</h2>
      <Small $muted>{what}</Small>
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
          Breaks and days off</Check>
      </Toggles>
      <Small $muted role="status">
        {short(first)} – {short(addDays(first, weeks * 7 - 1), true)}
      </Small>
      <Row>
        {format === "pdf" && (
          <Button as="a" $variant="primary" href={url} target="_blank" rel="noopener" onClick={onClose}>Open PDF</Button>
        )}
        <Button as="a" $variant={format === "pdf" ? "outline" : "primary"} href={url}
          download={`study-plan-${first}.${format}`} onClick={onClose}>Download</Button>
        <Button $variant="ghost" onClick={onClose}>Close</Button>
      </Row>
    </Modal>
  );
}
