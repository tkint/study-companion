import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Question, type StudyOverview } from "../api";
import { Status, useLoad } from "../components/common";
import { celebrate } from "../components/Confetti";
import { Icon } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { QuizResults } from "../components/QuizResults";
import { Reminders } from "../components/Reminders";
import { href } from "../router";

// Flashcards from the questions Claude saved, with spaced repetition: each answer is graded
// Again / Hard / Good / Easy and the server schedules the next review (app/study.py).

const GRADES = [
  { grade: 0, label: "Again", hint: "<10 min" },
  { grade: 1, label: "Hard", hint: "" },
  { grade: 2, label: "Good", hint: "" },
  { grade: 3, label: "Easy", hint: "" },
] as const;

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
      <p className="muted">
        Flashcards from the questions Claude saved. Cards you know come back less and less often.
      </p>
      <Reminders />
      <div className="study-bar">
        <span>
          <strong>{due}</strong> card{due === 1 ? "" : "s"} due · {overview.questions} in total
        </span>
        <span className="row tight">
          {due > 0 && <a className="btn btn-primary btn-sm" href={href.study({ due: true })}>Review all due</a>}
          <a className="btn btn-sm btn-ghost" href={href.time}>⏱ Study time</a>
          <a className="btn btn-sm btn-ghost" href={href.plan}>Catch-up plan</a>
        </span>
      </div>
      {!overview.courses.length && (
        <p className="empty">
          No questions yet. In the <a href={href.prompt()}>prompt builder</a>, pick “Quiz me” or “Flashcards” with
          “Save results to the app” on, and paste the prompt in Claude.
        </p>
      )}
      <ul className="course-list">
        {overview.courses.map((c) => (
          <li key={c.id} className="course-row static">
            <div>
              <a className="course-name" href={href.course(c.id)}>{c.fullname}</a>
              <div className="course-meta">
                <span>{c.questions} cards</span>
                {c.due > 0 && <span className="late">{c.due} due</span>}
                {c.new > 0 && <span>{c.new} new</span>}
                {c.notes > 0 && <span>{c.notes} summar{c.notes === 1 ? "y" : "ies"}</span>}
              </div>
            </div>
            <div className="row tight end">
              {c.due > 0 ? (
                <a className="btn btn-primary btn-sm" href={href.study({ course: c.id })}>Review {c.due}</a>
              ) : c.questions > 0 ? (
                <a className="btn btn-sm btn-ghost" href={href.study({ course: c.id, all: true })}>Practise all</a>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
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
    celebrate(null, right / done >= 0.6 ? 140 : 70);
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
        <p className="crumbs"><a href={back}>← Back</a></p>
        <div className="done-card">
          <span className="done-badge"><Icon name={done ? "trophy" : "leaf"} /></span>
          <h1>{done ? (right / done >= 0.8 ? "Brilliant session!" : right / done >= 0.5 ? "Well done!" : "Good effort!") : "All clear"}</h1>
          {done > 0 ? (
            <p>You reviewed {done} card{done === 1 ? "" : "s"} and knew {right}.
              {right < done && " The ones you missed will come back soon, that's how they stick."} Saved with the course.</p>
          ) : (
            <p className="muted">No cards are due here right now. Come back later, or practise them all.</p>
          )}
        </div>
        <div className="row">
          {!all && <a className="btn btn-primary" href={href.study({ course, section, all: true })}>Practise all cards</a>}
          {all && done > 0 && <button className="btn btn-primary" onClick={onRestart}>Again</button>}
          <a className="btn btn-ghost" href={href.study()}>Study overview</a>
        </div>
      </>
    );
  }

  return (
    <div className="flash-page">
      <div className="flash-top">
        <a href={back} className="crumbs">← Back</a>
        <span className="muted small">
          {queue.length} to go{done ? ` · ${right}/${done} known` : ""}
        </span>
      </div>
      <div className="progress" aria-hidden="true">
        <span style={{ width: `${(done / Math.max(1, cards.length)) * 100}%` }} />
      </div>
      <article className="flashcard" aria-live="polite">
        <div className="muted small flash-meta">
          {card.new ? <span className="tag">new</span> : card.lapses > 0 ? <span className="tag warn">missed {card.lapses}×</span> : null}
          {card.source && <span>{card.source}</span>}
        </div>
        <Markdown text={card.question} className="flash-q" />
        {choices.length > 0 && (
          <ol className="choices-list" type="A">
            {choices.map((c, i) => {
              const correct = shown && normalise(c) === normalise(card.answer);
              const wrong = shown && picked === i && !correct;
              return (
                <li key={i}>
                  <button type="button" className={`choice-btn${picked === i ? " picked" : ""}${correct ? " right" : ""}${wrong ? " wrong" : ""}`}
                    onClick={() => { setPicked(i); setShown(true); }} disabled={shown}>
                    {c}
                  </button>
                </li>
              );
            })}
          </ol>
        )}
        {shown ? (
          <div className="flash-a">
            <Markdown text={card.answer} />
            {card.explanation && <Markdown text={card.explanation} className="muted small" />}
          </div>
        ) : (
          <button className="btn btn-primary btn-block" onClick={() => setShown(true)}>Show answer</button>
        )}
      </article>
      {error && <p className="alert alert-error">{error}</p>}
      {shown && (
        <div className="grades" role="group" aria-label="How well did you know it?">
          {GRADES.map((g) => (
            <button key={g.grade} className={`grade g${g.grade}`} onClick={() => grade(g.grade)} disabled={busy}>
              <strong>{g.label}</strong>
              <span>{nextLabel(card, g.grade)}</span>
            </button>
          ))}
        </div>
      )}
      <p className="footnote">
        <button className="link danger" onClick={remove}>Delete this card</button>
      </p>
    </div>
  );
}

function normalise(s: string) {
  return s.replace(/[*_`]/g, "").trim().toLowerCase();
}
