import { useEffect, useRef, useState } from "react";
import styled from "styled-components";
import { api, type Dashboard as DashboardData, type Deadline, type Stats, type SyncState } from "../api";
import { Status, useLoad } from "../components/common";
import { CourseList } from "../components/CourseList";
import { DeadlineList } from "../components/DeadlineList";
import { Icon, type IconName } from "../components/Icon";
import { fromNow } from "../format";
import { href } from "../router";
import { minutes, PlanRow } from "./Plan";
import { tone as toneOf, type Tone } from "../styles/theme";
import { pop, rise } from "../styles/motion";
import { Alert, Banner, Button, Empty, Footnote, Late, List, Muted, SectionHead, Small, TextButton, Title, VisuallyHidden } from "../ui";

// The home page leads with what you did (streak, this week's wins, progress) and the next few
// things to do. Past items sit folded away under "catch up", so the page never opens on a
// wall of red.

const UP_NEXT = 5;

function replace(list: Deadline[], d: Deadline) {
  return list.map((x) => (x.id === d.id ? d : x));
}

// Two columns on a computer: today's work, and the courses beside it.
const Columns = styled.div`
  ${({ theme }) => theme.media.desktop} {
    display: grid;
    grid-template-columns: minmax(0, 3fr) minmax(300px, 2fr);
    gap: 0 40px;
    align-items: start;
  }
`;

const Side = styled.section`
  ${({ theme }) => theme.media.desktop} {
    position: sticky;
    top: calc(${({ theme }) => theme.layout.topbar} + 16px);
  }
`;

export default function Dashboard() {
  const { data, error, reload, setData } = useLoad(api.dashboard, []);

  function changed(d: Deadline) {
    if (!data) return;
    // Keep the item in place until the next load, so "Undo" stays under your thumb.
    setData({
      ...data,
      overdue: replace(data.overdue, d),
      this_week: replace(data.this_week, d),
      later: replace(data.later, d),
    });
  }

  if (!data) return <Status error={error} loading />;
  return (
    <>
      <SyncNotice sync={data.sync} onDone={reload} />
      <Hero data={data} />
      <Wins stats={data.stats} />

      <Columns>
        <div>
          <StudyToday data={data} onChange={reload} />
          <UpNext data={data} onChange={changed} />
          <CatchUpList items={data.overdue} onChange={changed} />
        </div>
        <Side id="progress">
          <Title><Icon name="book" /> Your courses</Title>
          <CourseList courses={data.courses} search={data.courses.length > 4} stack />
        </Side>
      </Columns>
      <Footnote>
        Study Companion {data.version} · <a href="/status">sync details</a>
      </Footnote>
    </>
  );
}

// ---------------------------------------------------------------- hero

function greeting(hour: number): { text: string; icon: IconName } {
  if (hour < 5) return { text: "Good night", icon: "moon" };
  if (hour < 12) return { text: "Good morning", icon: "sunrise" };
  if (hour < 18) return { text: "Good afternoon", icon: "sun" };
  return { text: "Good evening", icon: "moon" };
}

function cheer(stats: Stats): string {
  if (stats.studied_today && stats.streak > 1) return `${stats.streak} days in a row. You're on a roll!`;
  if (stats.studied_today) return "You already studied today. Nice work!";
  if (stats.streak > 0) return `Your ${stats.streak}-day streak is waiting. One small step keeps it going.`;
  if (stats.total.sections_studied + stats.total.deadlines_done + stats.total.cards_learned > 0)
    return "Welcome back! Pick one small thing to get going.";
  return "Every bit counts. Start with one small thing today.";
}

function overallProgress(data: DashboardData): { value: number; label: string } | null {
  const catchUp = data.catch_up;
  if (catchUp && catchUp.target_percent > 0) {
    return {
      value: Math.min(100, (100 * catchUp.percent) / catchUp.target_percent),
      label: catchUp.reached ? "target reached" : `of your ${catchUp.target_percent}% target`,
    };
  }
  const tracked = data.courses.filter((c) => c.progress != null);
  if (!tracked.length) return null;
  return {
    value: tracked.reduce((sum, c) => sum + (c.progress ?? 0), 0) / tracked.length,
    label: "course progress",
  };
}

const HeroCard = styled.section`
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 22px 24px;
  border-radius: ${({ theme }) => theme.radii.xl};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  box-shadow: ${({ theme }) => theme.shadows.card};
  animation: ${rise} .4s ease both;
  /* A calm tint in one corner: warm, not a glow. */
  background-image: radial-gradient(120% 140% at 100% 0%, ${({ theme }) => theme.colors.accentSoft} 0%, transparent 45%);
  ${({ theme }) => theme.media.small} { padding: 16px; gap: 12px; align-items: flex-start; }
`;

const HeroMain = styled.div`
  flex: 1;
  min-width: 0;
  h1 {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 0;
    font-size: 1.6rem;
    ${({ theme }) => theme.media.small} { font-size: 1.3rem; }
  }
  h1 > svg { width: 28px; height: 28px; color: ${({ theme }) => theme.colors.accent}; }
`;

const Cheer = styled.p`
  margin: 6px 0 16px;
  color: ${({ theme }) => theme.colors.textMuted};
`;

function Hero({ data }: { data: DashboardData }) {
  const g = greeting(new Date().getHours());
  const progress = overallProgress(data);
  return (
    <HeroCard aria-label="Welcome">
      <HeroMain>
        <h1><Icon name={g.icon} /> {g.text}!</h1>
        <Cheer>{cheer(data.stats)}</Cheer>
        <WeekStrip stats={data.stats} />
      </HeroMain>
      {progress && <Ring value={progress.value} label={progress.label} />}
    </HeroCard>
  );
}

const Week = styled.ol`
  list-style: none;
  display: flex;
  gap: 8px;
  margin: 0;
  padding: 0;
  ${({ theme }) => theme.media.small} { gap: 5px; }
`;

const Day = styled.li<{ $on: boolean; $today: boolean }>`
  display: grid;
  justify-items: center;
  gap: 4px;
  font-size: ${({ theme }) => theme.fontSizes.xs};
  font-weight: ${({ $today }) => ($today ? 800 : 500)};
  color: ${({ theme, $today }) => ($today ? theme.colors.primaryStrong : theme.colors.textMuted)};
  & > span:first-child {
    display: grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border-radius: ${({ theme }) => theme.radii.sm};
    color: ${({ theme }) => theme.colors.onPrimary};
    background: ${({ theme, $on }) => ($on ? theme.colors.primary : theme.colors.surfaceSunken)};
    border: 2px solid ${({ theme, $on, $today }) => ($on ? theme.colors.primary : $today ? theme.colors.primary : theme.colors.border)};
    ${({ theme }) => theme.media.small} { width: 26px; height: 26px; }
  }
  & > span:first-child svg { width: 16px; height: 16px; stroke-width: 3; }
`;

const PopDot = styled.span`
  animation: ${pop} .35s ${({ theme }) => theme.motion.spring} both;
`;

function WeekStrip({ stats }: { stats: Stats }) {
  return (
    <Week aria-label="Study days this week">
      {stats.week.map((d, i) => {
        const day = new Date(`${d.date}T12:00:00`);
        const today = i === stats.week.length - 1;
        const name = day.toLocaleDateString(undefined, { weekday: "long" });
        return (
          <Day key={d.date} $on={d.active} $today={today} title={`${name}: ${d.active ? "studied" : "no study"}`}>
            {d.active ? <PopDot><Icon name="check" /></PopDot> : <span />}
            <span>{day.toLocaleDateString(undefined, { weekday: "narrow" })}</span>
            <VisuallyHidden>{name}: {d.active ? "studied" : "no study"}</VisuallyHidden>
          </Day>
        );
      })}
    </Week>
  );
}

const RingBox = styled.div`
  position: relative;
  flex: none;
  width: 116px;
  height: 116px;
  ${({ theme }) => theme.media.small} { width: 90px; height: 90px; }
  svg { width: 100%; height: 100%; transform: rotate(-90deg); }
  circle { fill: none; stroke-width: 8; }
  circle:first-child { stroke: ${({ theme }) => theme.colors.surfaceSunken}; }
  circle:last-child {
    stroke: ${({ theme }) => theme.colors.success};
    stroke-linecap: round;
    transition: stroke-dashoffset 1.1s ${({ theme }) => theme.motion.ease};
  }
`;

const RingText = styled.div`
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  padding: 18px;
  text-align: center;
  strong { font-size: 1.45rem; line-height: 1; font-variant-numeric: tabular-nums; }
  span { margin-top: 2px; font-size: .66rem; line-height: 1.2; color: ${({ theme }) => theme.colors.textMuted}; }
  ${({ theme }) => theme.media.small} { padding: 12px; strong { font-size: 1.15rem; } }
`;

function Ring({ value, label }: { value: number; label: string }) {
  const r = 34;
  const c = 2 * Math.PI * r;
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const t = requestAnimationFrame(() => setShown(Math.max(0, Math.min(100, value))));
    return () => cancelAnimationFrame(t);
  }, [value]);
  const n = useCountUp(Math.round(value));
  return (
    <RingBox role="img" aria-label={`${Math.round(value)}% ${label}`}>
      <svg viewBox="0 0 80 80" aria-hidden="true">
        <circle cx="40" cy="40" r={r} />
        <circle cx="40" cy="40" r={r} strokeDasharray={c} strokeDashoffset={c * (1 - shown / 100)} />
      </svg>
      <RingText aria-hidden="true">
        <strong>{n}%</strong>
        <span>{label}</span>
      </RingText>
    </RingBox>
  );
}

// ---------------------------------------------------------------- wins

function useCountUp(target: number, ms = 700): number {
  const [n, setN] = useState(target);
  const from = useRef(0);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || target === 0) {
      setN(target);
      from.current = target;
      return;
    }
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      const eased = 1 - (1 - k) ** 3;
      setN(Math.round(a + (target - a) * eased));
      if (k < 1) raf = requestAnimationFrame(step);
      else from.current = target;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return n;
}

const WinList = styled(List)`
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 14px 0 0;
  @media (max-width: 760px) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
`;

const WinTile = styled.li<{ $tone: Tone }>`
  display: grid;
  justify-items: start;
  gap: 2px;
  padding: 14px 16px;
  border-radius: ${({ theme }) => theme.radii.lg};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  box-shadow: ${({ theme }) => theme.shadows.card};
  & > span:first-child {
    display: grid;
    place-items: center;
    width: 36px;
    height: 36px;
    margin-bottom: 6px;
    border-radius: ${({ theme }) => theme.radii.md};
    color: ${({ $tone }) => toneOf($tone).fg};
    background: ${({ $tone }) => toneOf($tone).bg};
  }
  & > span:first-child svg { width: 20px; height: 20px; }
  & > strong { font-size: 1.6rem; line-height: 1.1; font-variant-numeric: tabular-nums; }
`;

const WinLabel = styled.span`
  font-size: ${({ theme }) => theme.fontSizes.sm};
  font-weight: 650;
`;

function Win({ icon, tone, value, suffix = "", label, sub }: {
  icon: IconName; tone: Tone; value: number; suffix?: string; label: string; sub?: string;
}) {
  const n = useCountUp(value);
  return (
    <WinTile $tone={tone}>
      <span><Icon name={icon} /></span>
      <strong>{n}{suffix}</strong>
      <WinLabel>{label}</WinLabel>
      {sub && <Muted $small>{sub}</Muted>}
    </WinTile>
  );
}

function Wins({ stats }: { stats: Stats }) {
  const w = stats.this_week;
  const done = w.deadlines_done + w.sections_studied;
  return (
    <WinList aria-label="Your stats">
      <Win icon="flame" tone="coral" value={stats.streak} label={stats.streak === 1 ? "day streak" : "days streak"}
        sub={stats.best_streak > stats.streak ? `best ${stats.best_streak}` : stats.streak > 1 ? "your best yet!" : undefined} />
      <Win icon="checkCircle" tone="success" value={done} label="done this week"
        sub={`${w.sections_studied} section${w.sections_studied === 1 ? "" : "s"} · ${w.deadlines_done} task${w.deadlines_done === 1 ? "" : "s"}`} />
      <Win icon="cards" tone="sky" value={w.cards_reviewed} label="cards reviewed"
        sub={`${stats.total.cards_learned} learned in total`} />
      {w.quiz_percent != null ? (
        <Win icon="trophy" tone="accent" value={w.quiz_percent} suffix="%" label="quiz average"
          sub={`${w.quizzes} quiz${w.quizzes === 1 ? "" : "zes"} this week`} />
      ) : (
        <Win icon="note" tone="accent" value={stats.total.summaries} label={stats.total.summaries === 1 ? "summary" : "summaries"}
          sub="saved by your AI" />
      )}
    </WinList>
  );
}

// ---------------------------------------------------------------- today and next

function StudyToday({ data, onChange }: { data: DashboardData; onChange: () => void }) {
  const plan = data.plan;
  const today = plan.today;
  const due = data.study.due;
  if (!today && !due && !plan.sections_left) return null;
  return (
    <section id="today">
      <SectionHead>
        <Title><Icon name="target" /> Today's plan{today ? ` · ${minutes(today.minutes)}` : ""}</Title>
        <a href={href.plan}>Full plan <Icon name="arrow" /></a>
      </SectionHead>
      {due > 0 && (
        <Banner>
          <span><Icon name="cards" /> <span><strong>{due}</strong> flashcard{due === 1 ? "" : "s"} ready for review</span></span>
          <Button as="a" $variant="primary" $size="sm" href={href.study({ due: true })}>Let's go</Button>
        </Banner>
      )}
      {today ? (
        <List $gap="8px">
          {today.items.map((it, i) => <PlanRow key={i} item={it} onStudied={onChange} />)}
        </List>
      ) : (
        <Empty><Icon name="leaf" /> Nothing planned today. Enjoy it!</Empty>
      )}
      {plan.late > 0 && (
        <Small $muted>
          {plan.late} item{plan.late === 1 ? "" : "s"} this week won't fit before {plan.late === 1 ? "its" : "their"} deadline
          at {plan.hours_per_day} h a day. You can adjust that in the <a href={href.plan}>plan</a>.
        </Small>
      )}
    </section>
  );
}

function UpNext({ data, onChange }: { data: DashboardData; onChange: (d: Deadline) => void }) {
  const [all, setAll] = useState(false);
  const items = [...data.this_week, ...data.later];
  const shown = all ? items : data.this_week.slice(0, UP_NEXT);
  const more = items.length - shown.length;
  return (
    <section id="next">
      <SectionHead>
        <Title><Icon name="calendar" /> Coming up</Title>
        <a href={href.calendar}>Calendar <Icon name="arrow" /></a>
      </SectionHead>
      <DeadlineList items={shown}
        empty={data.later.length ? "Nothing due in the next 7 days. Enjoy the breathing room." : "Nothing scheduled. Enjoy the breathing room."}
        onChange={onChange} />
      {more > 0 && (
        <More $variant="soft" $size="sm" onClick={() => setAll(true)}>
          Show {more} more
        </More>
      )}
    </section>
  );
}

const More = styled(Button)`
  margin-top: 12px;
`;

const CatchUp = styled.details`
  margin-top: 28px;
  padding: 0 16px;
  border-radius: ${({ theme }) => theme.radii.lg};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  &[open] { padding-bottom: 16px; }
  & > summary {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 0;
    list-style: none;
    &::-webkit-details-marker { display: none; }
    &::after {
      content: "›";
      margin-left: auto;
      font-size: 1.4rem;
      color: ${({ theme }) => theme.colors.textMuted};
      transition: transform ${({ theme }) => theme.motion.base};
    }
    & > svg { width: 22px; height: 22px; color: ${({ theme }) => theme.colors.success}; }
    & > span { display: grid; gap: 2px; }
  }
  &[open] > summary::after { transform: rotate(90deg); }
  li { box-shadow: none; }
`;

const CaughtUp = styled(Empty)`
  margin-top: 24px;
`;

function CatchUpList({ items, onChange }: { items: Deadline[]; onChange: (d: Deadline) => void }) {
  const open = items.filter((d) => !d.done).length;
  if (!items.length) {
    return (
      <CaughtUp><Icon name="sparkles" /> You're all caught up on past work.</CaughtUp>
    );
  }
  return (
    <CatchUp id="catch-up">
      <summary>
        <Icon name="leaf" />
        <span>
          <strong>{open ? `${open} past item${open === 1 ? "" : "s"} to catch up on` : "Past items all handled"}</strong>
          <Muted $small>No rush: pick what matters to you and go at your own pace.</Muted>
        </span>
      </summary>
      <DeadlineList items={items} empty="" onChange={onChange} />
    </CatchUp>
  );
}

// ---------------------------------------------------------------- sync

const SyncPill = styled.div<{ $warn: boolean }>`
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
  margin: -8px 0 12px;
  font-size: ${({ theme }) => theme.fontSizes.sm};
  color: ${({ theme, $warn }) => ($warn ? theme.colors.warningText : theme.colors.textMuted)};
  & > span { display: inline-flex; align-items: center; gap: 6px; }
`;

function SyncNotice({ sync: initial, onDone }: { sync: SyncState; onDone: () => void }) {
  const [sync, setSync] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setSync(initial), [initial]);

  useEffect(() => {
    if (!sync.running) return;
    const t = window.setInterval(async () => {
      try {
        const s = await api.sync();
        setSync(s);
        if (!s.running) onDone();
      } catch {
        /* keep polling */
      }
    }, 3000);
    return () => window.clearInterval(t);
  }, [sync.running, onDone]);

  async function start() {
    setError(null);
    try {
      await api.startSync();
      setSync({ ...sync, running: true });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!sync.configured) {
    return (
      <Alert $tone="warning">
        Your source site is not connected yet. <a href="/settings">Open Settings</a> to add its address and token.
      </Alert>
    );
  }
  const run = sync.last_run;
  const failed = run && run.status !== "ok" && !sync.running;
  return (
    <SyncPill $warn={!!failed}>
      <span>
        <Icon name="refresh" spinning={sync.running} />
        {sync.running
          ? "Syncing with the source…"
          : run
            ? `Synced ${fromNow(run.finished_at ?? run.started_at)}${run.status === "ok" ? "" : ` (${run.status})`}`
            : "Not synced yet"}
        {error && <Late> · {error}</Late>}
      </span>
      {!sync.running && <TextButton onClick={start}>Sync now</TextButton>}
    </SyncPill>
  );
}
