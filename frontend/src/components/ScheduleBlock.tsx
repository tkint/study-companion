import styled from "styled-components";
import type { Schedule, ScheduleBlock } from "../api";
import { courseColor } from "../format";
import { href } from "../router";
import { minutes } from "../pages/Plan";
import { WorkMain, WorkRow, WorkTitle } from "./DeadlineList";
import type { Tone } from "../styles/theme";
import { Badge, Meta, Muted, Small, Stat, StatGrid, Swatch } from "../ui";

// One study block of the published schedule (app/planner/schedule.py), and the schedule's
// summary numbers. Used by the calendar page (block details) and nowhere else for now.

export const KIND_TONE: Record<ScheduleBlock["kind"], Tone> = {
  deep: "neutral",
  practice: "warning",
  recall: "primary",
  flashcards: "success",
};

/** "09:00" in the server's time zone (block times are planned in it). */
export function clock(ts: number, timeZone?: string): string {
  const opts: Intl.DateTimeFormatOptions = { hour: "2-digit", minute: "2-digit", hour12: false };
  try {
    return new Date(ts * 1000).toLocaleTimeString(undefined, { ...opts, timeZone });
  } catch {
    return new Date(ts * 1000).toLocaleTimeString(undefined, opts);
  }
}

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

const SummaryGrid = styled(StatGrid)`
  grid-template-columns: repeat(4, minmax(0, 1fr));
  @media (max-width: 640px) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
`;

export function Summary({ data }: { data: Schedule }) {
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

export function BlockRow({ block: b, timeZone }: { block: ScheduleBlock; timeZone?: string }) {
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

