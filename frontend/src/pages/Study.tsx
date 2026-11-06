import { useEffect, useMemo, useRef, useState } from "react";
import styled, { css } from "styled-components";
import { api, type Question, type StudyOverview } from "../api";
import { Status, useLoad } from "../components/common";
import { celebrate } from "../components/Confetti";
import { Icon } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { QuizResults } from "../components/QuizResults";
import { Reminders } from "../components/Reminders";
import { href } from "../router";
import { CourseMeta, CourseName, CourseRow } from "../components/CourseList";
import { pop, rise } from "../styles/motion";
import { Alert, Badge, Banner, Button, Crumbs, Empty, Footnote, Late, Lead, List, Muted, ProgressBar, Row, TextButton } from "../ui";

// Flashcards from the questions Claude saved, with spaced repetition: each answer is graded
// Again / Hard / Good / Easy and the server schedules the next review (app/study.py).

const GRADES = [
  { grade: 0, label: "Again", hint: "<10 min" },
  { grade: 1, label: "Hard", hint: "" },
  { grade: 2, label: "Good", hint: "" },
  { grade: 3, label: "Easy", hint: "" },
] as const;

const FlashPage = styled.div`
  max-width: 640px;
  margin: 0 auto;
`;

const FlashTop = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
`;

const Flashcard = styled.article`
  display: grid;
  align-content: start;
  gap: 14px;
  min-height: 40vh;
  margin: 14px 0;
  padding: 18px 20px 20px;
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.xl};
  box-shadow: ${({ theme }) => theme.shadows.elevated};
  animation: ${rise} .3s ease both;
`;

const FlashMeta = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-height: 1.2em;
  font-size: ${({ theme }) => theme.fontSizes.sm};
  color: ${({ theme }) => theme.colors.textMuted};
`;

const Question = styled(Markdown)`
  font-size: 1.15rem;
  font-weight: 650;
`;

const Answer = styled.div`
  display: grid;
  gap: 6px;
  padding-top: 12px;
  border-top: 2px dashed ${({ theme }) => theme.colors.border};
  animation: ${rise} .25s ease both;
`;

const Explanation = styled(Markdown)`
  font-size: ${({ theme }) => theme.fontSizes.sm};
  color: ${({ theme }) => theme.colors.textMuted};
`;

const Choices = styled.ol`
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
`;

const ChoiceButton = styled.button<{ $state?: "picked" | "right" | "wrong" }>`
  width: 100%;
  min-height: ${({ theme }) => theme.layout.tap};
  padding: 10px 14px;
  text-align: left;
  border-radius: ${({ theme }) => theme.radii.md};
  border: 2px solid ${({ theme }) => theme.colors.border};
  background: ${({ theme }) => theme.colors.surface};
  color: ${({ theme }) => theme.colors.textMain};
  transition: transform ${({ theme }) => theme.motion.fast}, border-color ${({ theme }) => theme.motion.base},
    background-color ${({ theme }) => theme.motion.base};
  &:hover:not(:disabled) { border-color: ${({ theme }) => theme.colors.primary}; }
  &:active:not(:disabled) { transform: scale(.98); }
  &:disabled { cursor: default; }
  ${({ $state, theme }) =>
    $state === "picked" ? css`border-color: ${theme.colors.primary};`
    : $state === "right" ? css`border-color: ${theme.colors.success}; background: ${theme.colors.successSoft};`
    : $state === "wrong" ? css`border-color: ${theme.colors.danger}; background: ${theme.colors.dangerSoft};`
    : ""}
`;

const Grades = styled.div`
  position: sticky;
  bottom: calc(${({ theme }) => theme.layout.tabbar} + 8px + env(safe-area-inset-bottom));
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  ${({ theme }) => theme.media.notPhone} { bottom: 12px; }
`;

const GRADE_TONES = ["dangerText", "warningText", "successText", "primaryStrong"] as const;

const Grade = styled.button<{ $grade: number }>`
  display: grid;
  justify-items: center;
  gap: 2px;
  min-height: 58px;
  padding: 8px 4px;
  border-radius: ${({ theme }) => theme.radii.md};
  border: 1px solid ${({ theme }) => theme.colors.border};
  background: ${({ theme }) => theme.colors.surface};
  color: ${({ theme }) => theme.colors.textMain};
  box-shadow: ${({ theme }) => theme.shadows.elevated};
  transition: transform ${({ theme }) => theme.motion.fast}, border-color ${({ theme }) => theme.motion.base};
  &:hover:not(:disabled) { border-color: ${({ theme, $grade }) => theme.colors[GRADE_TONES[$grade]]}; }
  &:active:not(:disabled) { transform: scale(.95); }
  &:disabled { opacity: .6; }
  strong { color: ${({ theme, $grade }) => theme.colors[GRADE_TONES[$grade]]}; }
  span { font-size: ${({ theme }) => theme.fontSizes.xs}; color: ${({ theme }) => theme.colors.textMuted}; }
`;

const DoneCard = styled.div`
  max-width: 520px;
  margin: 16px auto;
  padding: 28px 20px;
  text-align: center;
  border-radius: ${({ theme }) => theme.radii.xl};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  box-shadow: ${({ theme }) => theme.shadows.elevated};
  animation: ${rise} .4s ease both;
  h1 { margin-top: 14px; }
`;

const DoneBadge = styled.span`
  display: inline-grid;
  place-items: center;
  width: 72px;
  height: 72px;
  border-radius: ${({ theme }) => theme.radii.xl};
  color: ${({ theme }) => theme.colors.accentText};
  background: ${({ theme }) => theme.colors.accentSoft};
  animation: ${pop} .5s ${({ theme }) => theme.motion.spring} both;
  svg { width: 36px; height: 36px; }
`;

function nextLabel(q: Question, grade: number): string {
  if (grade === 0) return "<10 min";
  let days: number;
  if (grade === 1) days = q.reps ? Math.max(1, q.interval * 1.2) : 1;
  else if (q.reps === 0) days = grade === 2 ? 1 : 4;
  else if (q.reps === 1) days = grade === 2 ? 3 : 6;
  else days = Math.max(q.interval + 1, q.interval * 2.5 * (grade === 3 ? 1.3 : 1));
  days = Math.round(days);
  return days < 31 ? `${days} d` : `${Math.round(days / 30)} mo`;
}

export default function Study({ course, section, all, due }: {
  course?: number;
  section?: number;
  all?: boolean;
  due?: boolean;
}) {
  const { data, error, reload } = useLoad(() => api.cards({ course, section, all }), [course, section, all]);
  const [round, setRound] = useState(0);
  if (!data) return <Status error={error} loading />;
  if (!course && !section && !due) return <Overview overview={data.overview} due={data.questions.length} />;
  return <Session key={`${course}-${section}-${all}-${round}`} cards={data.questions} course={course}
    section={section} all={!!all} onRestart={() => { reload(); setRound((r) => r + 1); }} />;
}

function Overview({ overview, due }: { overview: StudyOverview; due: number }) {
  return (
    <>
      <h1>Study</h1>
      <Lead>
        Flashcards from the questions Claude saved. Cards you know come back less and less often.
      </Lead>
      <Reminders />
      <Banner $tone="neutral">
        <span>
          <strong>{due}</strong> card{due === 1 ? "" : "s"} due · {overview.questions} in total
        </span>
        <Row $tight $gap="6px">
          {due > 0 && <Button as="a" $variant="primary" $size="sm" href={href.study({ due: true })}>Review all due</Button>}
          <Button as="a" $variant="soft" $size="sm" href={href.time}>⏱ Study time</Button>
          <Button as="a" $variant="soft" $size="sm" href={href.plan}>Catch-up plan</Button>
        </Row>
      </Banner>
      {!overview.courses.length && (
        <Empty>
          <span>
            No questions yet. In the <a href={href.prompt()}>prompt builder</a>, pick “Quiz me” or “Flashcards” with
            “Save results to the app” on, and paste the prompt in Claude.
          </span>
        </Empty>
      )}
      <List>
        {overview.courses.map((c) => (
          <CourseRow as="li" key={c.id}>
            <div>
              <CourseName as="a" href={href.course(c.id)}>{c.fullname}</CourseName>
              <CourseMeta>
                <span>{c.questions} cards</span>
                {c.due > 0 && <Late>{c.due} due</Late>}
                {c.new > 0 && <span>{c.new} new</span>}
                {c.notes > 0 && <span>{c.notes} summar{c.notes === 1 ? "y" : "ies"}</span>}
              </CourseMeta>
            </div>
            <Row $tight $justify="flex-end">
              {c.due > 0 ? (
                <Button as="a" $variant="primary" $size="sm" href={href.study({ course: c.id })}>Review {c.due}</Button>
              ) : c.questions > 0 ? (
                <Button as="a" $variant="soft" $size="sm" href={href.study({ course: c.id, all: true })}>Practise all</Button>
              ) : null}
            </Row>
          </CourseRow>
        ))}
      </List>
      <QuizResults results={overview.recent_results} showCourse limit={5} />
    </>
  );
}

function Session({ cards, course, section, all, onRestart }: {
  cards: Question[];
  course?: number;
  section?: number;
  all: boolean;
  onRestart: () => void;
}) {
  const [queue, setQueue] = useState(cards);
  const [shown, setShown] = useState(false);
  const [picked, setPicked] = useState<number | null>(null);
  const [right, setRight] = useState(0);
  const [done, setDone] = useState(0);
  // Per course [known, reviewed]: a session across courses saves one result per course.
  const [tally, setTally] = useState<Record<number, [number, number]>>({});
  const seen = useRef(new Set<number>()); // only the first answer to a card counts in the score
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const card = queue[0];
  const courseId = course ?? (section ? cards[0]?.course_id : undefined);
  const back = section && courseId ? href.course(courseId, section) : courseId ? href.course(courseId) : href.study();

  // Record the session once, when the last card is graded.
  useEffect(() => {
    if (card || done === 0 || saved) return;
    setSaved(true);
    celebrate(null, right / done >= 0.6 ? 90 : 50);
    for (const [cid, [known, total]] of Object.entries(tally)) {
      api.saveResult({ course_id: Number(cid), section_id: section ?? null, score: known, total,
        topic: all ? "Flashcards: practice" : "Flashcards: review" }).catch(() => undefined);
    }
  }, [card, done, saved, section, all, tally, right]);

  const choices = useMemo(() => card?.choices ?? [], [card]);

  async function grade(g: number) {
    if (!card) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.review(card.id, g);
      if (!seen.current.has(card.id)) {
        seen.current.add(card.id);
        setDone((n) => n + 1);
        if (g >= 2) setRight((n) => n + 1);
        setTally((t) => {
          const [known, total] = t[card.course_id] ?? [0, 0];
          return { ...t, [card.course_id]: [known + (g >= 2 ? 1 : 0), total + 1] };
        });
      }
      // "Again" puts the card back at the end of this session.
      setQueue((q) => (g === 0 ? [...q.slice(1), updated] : q.slice(1)));
      setShown(false);
      setPicked(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!card || !window.confirm("Delete this card for good?")) return;
    await api.deleteQuestion(card.id);
    setQueue((q) => q.slice(1));
    setShown(false);
    setPicked(null);
  }

  if (!card) {
    return (
      <>
        <Crumbs><a href={back}>← Back</a></Crumbs>
        <DoneCard>
          <DoneBadge><Icon name={done ? "trophy" : "leaf"} /></DoneBadge>
          <h1>{done ? (right / done >= 0.8 ? "Brilliant session!" : right / done >= 0.5 ? "Well done!" : "Good effort!") : "All clear"}</h1>
          {done > 0 ? (
            <p>You reviewed {done} card{done === 1 ? "" : "s"} and knew {right}.
              {right < done && " The ones you missed will come back soon, that's how they stick."} Saved with the course.</p>
          ) : (
            <Lead>No cards are due here right now. Come back later, or practise them all.</Lead>
          )}
        </DoneCard>
        <Row $justify="center">
          {!all && <Button as="a" $variant="primary" href={href.study({ course, section, all: true })}>Practise all cards</Button>}
          {all && done > 0 && <Button $variant="primary" onClick={onRestart}>Again</Button>}
          <Button as="a" $variant="ghost" href={href.study()}>Study overview</Button>
        </Row>
      </>
    );
  }

  return (
    <FlashPage>
      <FlashTop>
        <Crumbs><a href={back}>← Back</a></Crumbs>
        <Muted $small>
          {queue.length} to go{done ? ` · ${right}/${done} known` : ""}
        </Muted>
      </FlashTop>
      <ProgressBar value={(done / Math.max(1, cards.length)) * 100} size="md" />
      <Flashcard key={card.id} aria-live="polite">
        <FlashMeta>
          {card.new ? <Badge $tone="sky">new</Badge> : card.lapses > 0 ? <Badge $tone="warning">missed {card.lapses}×</Badge> : null}
          {card.source && <span>{card.source}</span>}
        </FlashMeta>
        <Question text={card.question} />
        {choices.length > 0 && (
          <Choices type="A">
            {choices.map((c, i) => {
              const correct = shown && normalise(c) === normalise(card.answer);
              const wrong = shown && picked === i && !correct;
              return (
                <li key={i}>
                  <ChoiceButton type="button" $state={correct ? "right" : wrong ? "wrong" : picked === i ? "picked" : undefined}
                    onClick={() => { setPicked(i); setShown(true); }} disabled={shown}>
                    {c}
                  </ChoiceButton>
                </li>
              );
            })}
          </Choices>
        )}
        {shown ? (
          <Answer>
            <Markdown text={card.answer} />
            {card.explanation && <Explanation text={card.explanation} />}
          </Answer>
        ) : (
          <Button $variant="primary" $size="lg" $block onClick={() => setShown(true)}>Show answer</Button>
        )}
      </Flashcard>
      {error && <Alert>{error}</Alert>}
      {shown && (
        <Grades role="group" aria-label="How well did you know it?">
          {GRADES.map((g) => (
            <Grade key={g.grade} $grade={g.grade} onClick={() => grade(g.grade)} disabled={busy}>
              <strong>{g.label}</strong>
              <span>{nextLabel(card, g.grade)}</span>
            </Grade>
          ))}
        </Grades>
      )}
      <Footnote>
        <TextButton $danger onClick={remove}>Delete this card</TextButton>
      </Footnote>
    </FlashPage>
  );
}

function normalise(s: string) {
  return s.replace(/[*_`]/g, "").trim().toLowerCase();
}
