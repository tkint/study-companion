import { useState } from "react";
import styled from "styled-components";
import { api, type Deadline } from "../api";
import { celebrate } from "./Confetti";
import { Icon } from "./Icon";
import { courseColor, fromNow, sourceLabel, when } from "../format";
import { href } from "../router";
import { PrefsMenu, PrefTags } from "./Prefs";
import { Badge, Button, Card, Empty, Late, List, Meta, Muted, Swatch } from "../ui";

/** A row of work: the course stripe, the text, and actions on the right. Shared with the plan. */
export const WorkRow = styled(Card)<{ $late?: boolean; $done?: boolean }>`
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 14px 16px;
  ${({ $late, theme }) => $late && `border-color: color-mix(in srgb, ${theme.colors.warning} 50%, ${theme.colors.border});`}
  ${({ $done }) => $done && "opacity: .6;"}
`;

export const WorkMain = styled.div`
  flex: 1 1 200px;
  min-width: 0;
`;

export const WorkTitle = styled.div<{ $done?: boolean }>`
  font-weight: 650;
  overflow-wrap: anywhere;
  text-decoration: ${({ $done }) => ($done ? "line-through" : "none")};
  a { color: ${({ theme }) => theme.colors.textMain}; }
`;

export const WorkActions = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-left: auto;
`;

const When = styled.div`
  font-size: ${({ theme }) => theme.fontSizes.sm};
`;

export function DeadlineItem({
  d,
  onChange,
  showCourse = true,
}: {
  d: Deadline;
  onChange?: (d: Deadline) => void;
  showCourse?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const now = Date.now() / 1000;
  const overdue = d.due_at < now && !d.done;
  const late = overdue && d.mandatory && !d.ignored;

  async function toggle(e: React.MouseEvent<HTMLButtonElement>) {
    const button = e.currentTarget;
    setBusy(true);
    try {
      await api.setDone(d.id, !d.done);
      if (!d.done) celebrate(button, 40);
      onChange?.({ ...d, done: !d.done, done_by: d.done ? null : "you" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <WorkRow as="li" $late={late} $done={d.done || d.ignored}>
      <Swatch style={{ background: courseColor(d.course_id) }} aria-hidden="true" />
      <WorkMain>
        <WorkTitle $done={d.done}>{d.name}</WorkTitle>
        <Meta>
          {showCourse && d.course_id != null && (
            <a href={href.course(d.course_id)}>{d.course_shortname || d.course_name}</a>
          )}
          <Badge>{sourceLabel(d.source)}</Badge>
          {d.closed && <Badge $tone="warning">closed</Badge>}
          <PrefTags state={d} />
          {d.done && <Badge $tone="success" $pop>done{d.done_by === "moodle" ? " at the source" : ""}</Badge>}
        </Meta>
        <When>
          <time dateTime={new Date(d.due_at * 1000).toISOString()}>{when(d.due_at)}</time>
          {late ? <Late> · {fromNow(d.due_at)}</Late> : <Muted> · {fromNow(d.due_at)}</Muted>}
        </When>
      </WorkMain>
      <WorkActions>
        {d.url && (
          <Button as="a" $size="sm" $variant="ghost" href={d.url} target="_blank" rel="noopener noreferrer">
            Source ↗
          </Button>
        )}
        {d.done_by !== "moodle" && (
          <Button $size="sm" $variant={d.done ? "ghost" : "success"} onClick={toggle} disabled={busy}>
            {d.done ? "Undo" : <><Icon name="check" /> Done</>}
          </Button>
        )}
        {!d.done && (
          <PrefsMenu state={d} label={d.name} save={(p) => api.setDeadlinePrefs(d.id, p)}
            onChange={(st) => onChange?.({ ...d, ...st, id: d.id })} />
        )}
      </WorkActions>
    </WorkRow>
  );
}

export function DeadlineList({
  items,
  empty,
  onChange,
  showCourse,
}: {
  items: Deadline[];
  empty: string;
  onChange?: (d: Deadline) => void;
  showCourse?: boolean;
}) {
  if (!items.length) return empty ? <Empty>{empty}</Empty> : null;
  return (
    <List>
      {items.map((d) => (
        <DeadlineItem key={d.id} d={d} onChange={onChange} showCourse={showCourse} />
      ))}
    </List>
  );
}
