import { useState } from "react";
import styled from "styled-components";
import { api, type Plan as PlanData, type PlanItem, type PlanSlot } from "../api";
import { Status, useLoad } from "../components/common";
import { celebrate } from "../components/Confetti";
import { WorkActions, WorkMain, WorkRow, WorkTitle } from "../components/DeadlineList";
import { Icon } from "../components/Icon";
import { PrefsMenu } from "../components/Prefs";
import { courseColor, sourceLabel, when } from "../format";
import { href } from "../router";
import {
  Alert, Badge, Button, Check, Crumbs, Empty, Field, Fold, Late, Lead, List, Meta, Muted, ProgressBar, Row, Select, Small, Stat,
  StatGrid, Swatch, Toggles,
} from "../ui";

// The rule-based catch-up plan (app/planner): the mandatory sections left to study and open
// deadlines, ordered by urgency and spread over the days at your hours per day. Backlog
// beyond your catch-up target (e.g. 60%) is listed apart, as "if you have time".

const TARGETS = [40, 50, 60, 70, 80, 90, 100];

export function minutes(m: number): string {
  const h = Math.floor(m / 60);
  const r = m % 60;
  if (!h) return `${r} min`;
  return r ? `${h} h ${String(r).padStart(2, "0")}` : `${h} h`;
}

const Side = styled(WorkActions)`
  flex-direction: column;
  align-items: flex-end;
  flex: none;
  & > strong { font-variant-numeric: tabular-nums; white-space: nowrap; }
`;

const Controls = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  max-width: 660px;
  gap: 12px;
  margin: 12px 0 8px;
  & > ${Field} { margin-top: 0; }
`;

export const DayHead = styled.h2`
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  & > span:last-child {
    font-size: ${({ theme }) => theme.fontSizes.sm};
    font-weight: 600;
    color: ${({ theme }) => theme.colors.textMuted};
  }
`;

const Target = styled.div`
  margin: 12px 0 16px;
`;

function dayLabel(iso: string, today: string): string {
  if (iso === today) return "Today";
  const d = new Date(`${iso}T12:00:00`);
  const t = new Date(`${today}T12:00:00`);
  if ((d.getTime() - t.getTime()) / 86400000 === 1) return "Tomorrow";
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
}

export function PlanRow({ item, onStudied, onPrefs }: {
  item: PlanSlot | PlanItem;
  onStudied?: (sectionId: number) => void;
  onPrefs?: () => void;
}) {
  const slot = "minutes_today" in item ? item : null;
  const [busy, setBusy] = useState(false);
  const isSection = item.kind === "section";
  async function studied(e: React.MouseEvent<HTMLButtonElement>) {
    if (!item.section_id) return;
    const button = e.currentTarget;
    setBusy(true);
    try {
      await api.setStudied(item.section_id, true);
      celebrate(button, 40);
      onStudied?.(item.section_id);
    } finally {
      setBusy(false);
    }
  }
  const link = isSection && item.course_id
    ? href.course(item.course_id, item.section_id ?? undefined)
    : item.course_id ? href.course(item.course_id) : undefined;
  return (
    <WorkRow as="li" $late={!!slot?.late || item.overdue}>
      <Swatch style={{ background: courseColor(item.course_id) }} aria-hidden="true" />
      <WorkMain>
        <WorkTitle>
          {link ? <a href={link}>{item.title}</a> : item.title}
          {slot && slot.parts > 1 && <Muted> · part {slot.part}/{slot.parts}</Muted>}
        </WorkTitle>
        <Meta>
          <strong>{item.course_short || item.course_name}</strong>
          <Badge>{isSection ? `Section ${item.section_number}` : sourceLabel(item.kind)}</Badge>
          {isSection && item.pages > 0 && <span>{item.pages} p.</span>}
          {!item.mandatory && <Badge $dashed>optional</Badge>}
          {item.has_summary && <Badge $tone="primary">notes</Badge>}
          {item.questions > 0 && <Badge $tone="sky">{item.questions} cards</Badge>}
          {slot?.late && <Badge $tone="warning">late</Badge>}
        </Meta>
        {item.needed_by && (
          <Small $muted={!item.overdue}>
            {item.overdue ? <Late>Overdue since {when(item.needed_by)}</Late> : (
              <>{isSection ? `Needed for “${item.needed_for}” by ` : "Due "}{when(item.needed_by)}</>
            )}
          </Small>
        )}
      </WorkMain>
      <Side>
        <strong>{minutes(slot ? slot.minutes_today : item.minutes)}</strong>
        {isSection && onStudied && (
          <Button $size="sm" $variant="success" onClick={studied} disabled={busy}><Icon name="check" /> Studied</Button>
        )}
        {!isSection && item.url && (
          <Button as="a" $size="sm" $variant="ghost" href={item.url} target="_blank" rel="noopener noreferrer">Source ↗</Button>
        )}
        {onPrefs && (item.section_id || item.deadline_id) && (
          <PrefsMenu state={{ mandatory: item.mandatory, ignored: false }} label={item.title} onChange={onPrefs}
            save={(p) => (item.section_id ? api.setSectionPrefs(item.section_id, p) : api.setDeadlinePrefs(item.deadline_id!, p))} />
        )}
      </Side>
    </WorkRow>
  );
}

export default function Plan() {
  const [days, setDays] = useState(14);
  const [optional, setOptional] = useState(false);
  const [beyond, setBeyond] = useState(false);
  const { data, error, reload } = useLoad(() => api.plan(days, undefined, { optional, beyond }), [days, optional, beyond]);
  const [hours, setHours] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  if (!data) return <Status error={error} loading />;
  const h = hours ?? data.hours_per_day;
  const target = data.target_percent;

  async function saveTarget(v: number) {
    setSaving(true);
    try {
      await api.setTarget(v);
      reload();
    } finally {
      setSaving(false);
    }
  }

  async function saveHours(v: number) {
    setHours(v);
    setSaving(true);
    try {
      await api.setHours(v);
      reload();
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Crumbs><a href={href.dashboard}>← Today</a></Crumbs>
      <h1>Catch-up plan</h1>
      <Lead $small>
        The mandatory work ahead of you, ordered by the deadline each piece is needed for, plus enough of what you
        missed to reach your goal. You don't have to catch up on everything. Times are estimates from page counts;
        use ⋯ to mark something optional or let it go.
      </Lead>
      <Row $tight>
        <Button as="a" $variant="soft" $size="sm" href={href.schedule}>Timed schedule and .ics export →</Button>
      </Row>
      <Controls>
        <Field>
          Hours per day
          <Select value={h} disabled={saving} onChange={(e) => saveHours(Number(e.target.value))}>
            {[0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8].concat(
              [0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8].includes(h) ? [] : [h]).sort((a, b) => a - b).map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </Select>
        </Field>
        <Field>
          Days
          <Select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 14, 21, 30, 60].map((v) => <option key={v} value={v}>{v}</option>)}
          </Select>
        </Field>
        <Field>
          Catch-up goal
          <Select value={target} disabled={saving} onChange={(e) => saveTarget(Number(e.target.value))}>
            {TARGETS.concat(TARGETS.includes(target) ? [] : [target]).sort((a, b) => a - b).map((v) => (
              <option key={v} value={v}>{v}%</option>
            ))}
          </Select>
        </Field>
      </Controls>
      <Toggles>
        <Check><input type="checkbox" checked={optional} onChange={(e) => setOptional(e.target.checked)} />
          Include optional work</Check>
        <Check><input type="checkbox" checked={beyond} onChange={(e) => setBeyond(e.target.checked)} />
          Plan beyond my goal</Check>
      </Toggles>
      <Summary plan={data} />
      <TargetBar plan={data} />
      {data.notes.map((n, i) => <Alert key={i} $tone="warning">{n}</Alert>)}
      {!data.days.length && !data.unscheduled.length && (
        <Empty><Icon name="sparkles" /> Nothing left to catch up on.</Empty>
      )}
      {data.days.map((d) => (
        <section key={d.date}>
          <DayHead>
            <span>{dayLabel(d.date, data.today)}</span>
            <span>{minutes(d.minutes)}</span>
          </DayHead>
          <List $gap="8px">
            {d.items.map((it, i) => <PlanRow key={i} item={it} onStudied={reload} onPrefs={reload} />)}
          </List>
        </section>
      ))}
      {data.unscheduled.length > 0 && (
        <section>
          <DayHead>
            <span>Doesn't fit in {days} days</span>
            <span>{minutes(data.unscheduled_minutes)}</span>
          </DayHead>
          <List $gap="8px">
            {data.unscheduled.map((it, i) => <PlanRow key={i} item={it} onStudied={reload} onPrefs={reload} />)}
          </List>
        </section>
      )}
      {data.beyond_target.length > 0 && (
        <Fold>
          <summary>
            Beyond your {target}% goal: {data.beyond_target.length} item{data.beyond_target.length === 1 ? "" : "s"},{" "}
            {minutes(data.beyond_target_minutes)} (only if you have time)
          </summary>
          <List $gap="8px">
            {data.beyond_target.map((it, i) => <PlanRow key={i} item={it} onStudied={reload} onPrefs={reload} />)}
          </List>
        </Fold>
      )}
    </>
  );
}

function Summary({ plan }: { plan: PlanData }) {
  const p = plan.progress;
  return (
    <StatGrid aria-label="Plan summary">
      <Stat><strong>{Math.round(p.percent)}%</strong><span>caught up</span></Stat>
      <Stat $tone="primary"><strong>{Math.round(plan.projected_percent)}%</strong><span>with this plan</span></Stat>
      <Stat $tone={plan.late ? "danger" : undefined}>
        <strong>{minutes(plan.total_minutes)}</strong>
        <span>{plan.late ? `${plan.late} late` : "planned"}</span>
      </Stat>
    </StatGrid>
  );
}

// Progress on the mandatory work, with a mark at your goal.
function TargetBar({ plan }: { plan: PlanData }) {
  const p = plan.progress;
  const left = p.left_minutes_to_target;
  return (
    <Target>
      <ProgressBar value={p.percent} size="lg" tone={p.reached ? "success" : "primary"} marker={p.target_percent}
        label="Mandatory work done" />
      <Small $muted>
        {p.reached
          ? `Goal reached: ${Math.round(p.percent)}% of the mandatory work is done (goal ${p.target_percent}%). Anything more is a bonus.`
          : `${p.done_items} of ${p.total_items} mandatory items done. ${minutes(left)} more to reach your ${p.target_percent}% goal.`}
        {plan.ignored > 0 && ` ${plan.ignored} ignored.`}
        {plan.optional_left_out > 0 && ` ${plan.optional_left_out} optional left out.`}
      </Small>
    </Target>
  );
}
