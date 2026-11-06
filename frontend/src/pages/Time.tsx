import { useEffect, useState } from "react";
import { api, type TimeSummary } from "../api";
import styled from "styled-components";
import { Status, useLoad } from "../components/common";
import { courseColor, minutesLabel, when } from "../format";
import { href } from "../router";
import { Button, Card, Field, FieldRow, Input, Lead, List, Muted, ProgressBar, Row, Select, Small, Stat, StatGrid, Swatch } from "../ui";

const TimerCard = styled(Card).attrs({ as: "section" as const, $pad: "lg" as const })`
  margin-top: 16px;
  text-align: center;
  & > ${Field} { text-align: left; }
`;

const Clock = styled.div`
  margin: 8px 0 4px;
  font-size: 3.2rem;
  font-weight: 800;
  line-height: 1.1;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
  color: ${({ theme }) => theme.colors.primaryStrong};
`;

const Message = styled.p`
  margin: 10px 0 0;
  font-weight: 650;
`;

const Chart = styled(Card)`
  padding: 12px 12px 28px;
`;

const Plot = styled.div`
  position: relative;
  display: grid;
  grid-template-columns: repeat(14, 1fr);
  align-items: end;
  gap: 4px;
  height: 120px;
`;

const Bar = styled.div`
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
`;

const BarFill = styled.span<{ $met: boolean }>`
  display: block;
  min-height: 2px;
  border-radius: 6px 6px 2px 2px;
  background: ${({ theme, $met }) => ($met ? theme.colors.success : theme.colors.primary)};
  opacity: ${({ $met }) => ($met ? 1 : 0.6)};
  transition: height ${({ theme }) => theme.motion.slow} ease;
`;

const BarDay = styled.small<{ $today: boolean }>`
  position: absolute;
  bottom: -20px;
  left: 0;
  right: 0;
  text-align: center;
  font-size: ${({ theme }) => theme.fontSizes.xs};
  font-weight: ${({ $today }) => ($today ? 800 : 500)};
  color: ${({ theme, $today }) => ($today ? theme.colors.textMain : theme.colors.textMuted)};
`;

const Goal = styled.div`
  position: absolute;
  left: 0;
  right: 0;
  border-top: 2px dashed ${({ theme }) => theme.colors.success};
  opacity: .7;
  pointer-events: none;
`;

const Entry = styled(Card).attrs({ as: "li" as const, $pad: "sm" as const })`
  display: flex;
  align-items: center;
  gap: 10px;
  & > ${Swatch} { width: 10px; height: 10px; border-radius: 50%; align-self: center; }
  & > span:nth-child(2) { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  & > strong { font-variant-numeric: tabular-nums; }
`;

const ManualForm = styled(Card).attrs({ as: "form" as const })``;

// Study time: a timer you start and stop (it survives reloads and closing the app), manual
// entries, and the totals: today against the daily goal, this week, the streak.
// Claude logs its sessions too (MCP tool log_study_time). Backend: app/study_time.py.

const TIMER_KEY = "study-timer";
const MAX_MINUTES = 12 * 60;

interface Timer {
  start: number; // ms
  course: number | null;
}

function loadTimer(): Timer | null {
  try {
    const raw = localStorage.getItem(TIMER_KEY);
    const t = raw ? JSON.parse(raw) : null;
    return t && typeof t.start === "number" ? { start: t.start, course: t.course ?? null } : null;
  } catch {
    return null;
  }
}

function saveTimer(t: Timer | null) {
  try {
    if (t) localStorage.setItem(TIMER_KEY, JSON.stringify(t));
    else localStorage.removeItem(TIMER_KEY);
  } catch {
    /* private mode: the timer just won't survive a reload */
  }
}

function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

const weekday = new Intl.DateTimeFormat(navigator.language || "en", { weekday: "narrow" });
const longDay = new Intl.DateTimeFormat(navigator.language || "en", { weekday: "long", day: "numeric", month: "short" });
const day = (iso: string) => new Date(`${iso}T12:00:00`);

function encouragement(s: TimeSummary): string {
  const goal = s.goal_minutes_per_day;
  if (goal && s.today_minutes >= goal) return "Daily goal reached. Well done! 🎉";
  if (s.today_minutes > 0) return "Nice start today. Every minute counts.";
  if (s.streak_days > 0) return `Keep your ${s.streak_days}-day streak going with a short session today.`;
  return "A short session is a great way to start. Try 25 minutes.";
}

export default function Time() {
  const { data, error, setData } = useLoad(() => api.studyTime(), []);
  const courses = useLoad(() => api.dashboard().then((d) => d.courses), []);
  const [timer, setTimer] = useState<Timer | null>(loadTimer);
  const [now, setNow] = useState(Date.now());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [manual, setManual] = useState({ minutes: "30", course: "", note: "" });

  useEffect(() => {
    if (!timer) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [timer]);

  if (!data) return <Status error={error} loading />;
  const goal = data.goal_minutes_per_day;
  const max = Math.max(goal * 1.15, ...data.days.map((d) => d.minutes), 1);
  const courseList = courses.data ?? [];

  const save = async (e: Parameters<typeof api.logTime>[0]) => {
    setBusy(true);
    setMessage(null);
    try {
      const before = data.today_minutes;
      const r = await api.logTime(e);
      setData(r.summary);
      const reached = goal > 0 && before < goal && r.summary.today_minutes >= goal;
      setMessage(reached ? "Daily goal reached! 🎉" : `Saved ${minutesLabel(r.entry.minutes)}.`);
      return true;
    } catch (err) {
      setMessage((err as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const start = () => {
    const t = { start: Date.now(), course: manual.course ? Number(manual.course) : null };
    saveTimer(t);
    setTimer(t);
    setNow(Date.now());
    setMessage(null);
  };

  const stop = async () => {
    if (!timer) return;
    const minutes = Math.min(MAX_MINUTES, Math.round((Date.now() - timer.start) / 60000));
    if (minutes < 1) {
      saveTimer(null);
      setTimer(null);
      setMessage("Less than a minute: not saved.");
      return;
    }
    if (await save({ minutes, course_id: timer.course, started_at: Math.floor(timer.start / 1000), source: "timer" })) {
      saveTimer(null);
      setTimer(null);
    }
  };

  const cancel = () => {
    saveTimer(null);
    setTimer(null);
  };

  const addManual = async (ev: React.FormEvent) => {
    ev.preventDefault();
    const minutes = Number(manual.minutes);
    if (!Number.isFinite(minutes) || minutes < 1) return setMessage("Enter the minutes you studied.");
    await save({ minutes: Math.round(minutes), course_id: manual.course ? Number(manual.course) : null,
      note: manual.note.trim(), source: "manual" });
  };

  const remove = async (id: number) => {
    await api.deleteTime(id);
    setData(await api.studyTime());
  };

  const timerCourse = timer?.course != null ? courseList.find((c) => c.id === timer.course) : undefined;

  return (
    <>
      <h1>Study time</h1>
      <Lead>{encouragement(data)}</Lead>

      <StatGrid>
        <Stat $tone={goal && data.today_minutes >= goal ? "success" : undefined}>
          <strong>{minutesLabel(data.today_minutes)}</strong>
          <span>today{goal ? ` · goal ${minutesLabel(goal)}` : ""}</span>
        </Stat>
        <Stat>
          <strong>{minutesLabel(data.week_minutes)}</strong>
          <span>this week</span>
        </Stat>
        <Stat $tone={data.streak_days > 0 ? "coral" : undefined}>
          <strong>{data.streak_days}</strong>
          <span>day{data.streak_days === 1 ? "" : "s"} in a row</span>
        </Stat>
      </StatGrid>
      {goal > 0 && (
        <ProgressBar value={(100 * data.today_minutes) / goal} size="md"
          tone={data.today_minutes >= goal ? "success" : "primary"} label="Today against your daily goal" />
      )}

      <TimerCard aria-live="polite">
        {timer ? (
          <>
            <Clock>{clock(now - timer.start)}</Clock>
            <Muted>{timerCourse ? timerCourse.fullname : "General study"} · started {when(Math.floor(timer.start / 1000))}</Muted>
            <Row $justify="center">
              <Button $variant="primary" onClick={stop} disabled={busy}>Stop and save</Button>
              <Button $variant="ghost" onClick={cancel} disabled={busy}>Discard</Button>
            </Row>
          </>
        ) : (
          <>
            <Field>
              <span>Course</span>
              <Select value={manual.course} onChange={(e) => setManual({ ...manual, course: e.target.value })}>
                <option value="">General study</option>
                {courseList.map((c) => <option key={c.id} value={c.id}>{c.fullname}</option>)}
              </Select>
            </Field>
            <Row>
              <Button $variant="primary" $size="lg" $block onClick={start}>▶ Start the timer</Button>
            </Row>
            <Small $muted>The timer keeps running if you close the app.</Small>
          </>
        )}
        {message && <Message>{message}</Message>}
      </TimerCard>

      <h2>Last 14 days</h2>
      <Chart role="img"
        aria-label={`Minutes per day: ${data.days.map((d) => `${d.date} ${d.minutes}`).join(", ")}`}>
        <Plot>
          {goal > 0 && <Goal style={{ bottom: `${(100 * goal) / max}%` }} title={`Goal ${minutesLabel(goal)}`} />}
          {data.days.map((d) => (
            <Bar key={d.date} title={`${longDay.format(day(d.date))}: ${minutesLabel(d.minutes)}`}>
              <BarFill $met={!!goal && d.minutes >= goal} style={{ height: `${(100 * d.minutes) / max}%` }} />
              <BarDay $today={d.date === data.today}>{weekday.format(day(d.date))}</BarDay>
            </Bar>
          ))}
        </Plot>
      </Chart>
      <Small $muted>
        {data.best_day ? <>Best day: {minutesLabel(data.best_day.minutes)} on {longDay.format(day(data.best_day.date))}. </> : null}
        {data.total_minutes > 0 && <>Total so far: {minutesLabel(data.total_minutes)}.</>}
        {" "}Daily goal comes from the <a href={href.plan}>catch-up plan</a>'s hours per day.
      </Small>

      {data.courses.length > 0 && (
        <>
          <h2>Last 7 days by course</h2>
          <List $gap="6px">
            {data.courses.map((c) => (
              <Entry key={c.course_id ?? 0}>
                <Swatch style={{ background: courseColor(c.course_id) }} />
                <span>{c.course_name || "General study"}</span>
                <strong>{minutesLabel(c.minutes)}</strong>
              </Entry>
            ))}
          </List>
        </>
      )}

      <h2>Add time by hand</h2>
      <ManualForm onSubmit={addManual}>
        <FieldRow $min="120px">
          <Field>
            <span>Minutes</span>
            <Input type="number" min={1} max={MAX_MINUTES} inputMode="numeric" value={manual.minutes}
              onChange={(e) => setManual({ ...manual, minutes: e.target.value })} />
          </Field>
          <Field>
            <span>Course</span>
            <Select value={manual.course} onChange={(e) => setManual({ ...manual, course: e.target.value })}>
              <option value="">General study</option>
              {courseList.map((c) => <option key={c.id} value={c.id}>{c.fullname}</option>)}
            </Select>
          </Field>
        </FieldRow>
        <Field>
          <span>Note (optional)</span>
          <Input type="text" maxLength={200} value={manual.note}
            onChange={(e) => setManual({ ...manual, note: e.target.value })} placeholder="e.g. read chapter 3" />
        </Field>
        <Row>
          <Button $variant="primary" type="submit" disabled={busy}>Add</Button>
        </Row>
      </ManualForm>

      {data.recent.length > 0 && (
        <>
          <h2>Recent sessions</h2>
          <List $gap="6px">
            {data.recent.slice(0, 8).map((e) => (
              <Entry key={e.id}>
                <Swatch style={{ background: courseColor(e.course_id) }} />
                <span>
                  {e.course_shortname || e.course_name || "General study"}
                  {e.note && <Muted> · {e.note}</Muted>}
                  <br />
                  <Muted $small>
                    {when(e.started_at)} · {e.source === "claude" ? "logged by your AI" : e.source === "timer" ? "timer" : "added by hand"}
                  </Muted>
                </span>
                <strong>{minutesLabel(e.minutes)}</strong>
                <Button $variant="ghost" $size="sm" onClick={() => remove(e.id)} aria-label="Delete this session">✕</Button>
              </Entry>
            ))}
          </List>
        </>
      )}
    </>
  );
}
