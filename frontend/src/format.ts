const locale = navigator.language || "en";

const dateTime = new Intl.DateTimeFormat(locale, {
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const dateTimeYear = new Intl.DateTimeFormat(locale, {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const relative = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });

export function when(ts: number, now = Date.now() / 1000): string {
  const d = new Date(ts * 1000);
  const sameYear = d.getFullYear() === new Date(now * 1000).getFullYear();
  return (sameYear ? dateTime : dateTimeYear).format(d);
}

export function fromNow(ts: number, now = Date.now() / 1000): string {
  const diff = ts - now;
  const abs = Math.abs(diff);
  if (abs < 3600) return relative.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return relative.format(Math.round(diff / 3600), "hour");
  if (abs < 30 * 86400) return relative.format(Math.round(diff / 86400), "day");
  return relative.format(Math.round(diff / (7 * 86400)), "week");
}

export function size(bytes: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

export function sourceLabel(source: string): string {
  return { assign: "Assignment", quiz: "Quiz", event: "Event" }[source] ?? source;
}

// Stable colour per course, from a palette readable in light and dark mode.
const PALETTE = ["#2563eb", "#db2777", "#059669", "#d97706", "#7c3aed", "#0891b2", "#dc2626", "#65a30d"];
export function courseColor(id: number | null): string {
  return id == null ? "#64748b" : PALETTE[Math.abs(id) % PALETTE.length];
}

export function minutesLabel(m: number): string {
  const h = Math.floor(m / 60);
  const r = m % 60;
  if (h && r) return `${h} h ${String(r).padStart(2, "0")}`;
  return h ? `${h} h` : `${r} min`;
}
