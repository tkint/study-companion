import { useEffect, useMemo, useRef, useState } from "react";
import { request, ApiError } from "../api";
import { Status, useLoad } from "../components/common";
import { when } from "../format";

// Types of /api/prompt/* (backend: app/prompts and app/api/prompts.py).
interface PromptCourse {
  id: number;
  fullname: string;
  shortname: string;
  lang: string;
  next_deadline: number | null;
  sections: { id: number; number: number; name: string }[];
}
interface Choice {
  id: string;
  title: string;
}
interface Goal extends Choice {
  description: string;
  topic: "required" | "optional" | "none";
}
interface Options {
  today: string;
  timezone: string;
  courses: PromptCourse[];
  goals: Goal[];
  depths: Choice[];
  languages: Choice[];
}
interface Built {
  summary: { sections: number; files: number; readable_files: number; pages: number; prompts: number };
  courses: { id: number; fullname: string; sections: number; files: number; pages: number; note: string }[];
  prompts: { title: string; text: string }[];
}

type Period = "2months" | "4weeks" | "deadline" | "all" | "dates" | "sections";
type TimeMode = "none" | "total" | "daily";

const PERIODS: { id: Period; label: string }[] = [
  { id: "2months", label: "Last 2 months" },
  { id: "4weeks", label: "Last 4 weeks" },
  { id: "deadline", label: "Until next deadline" },
  { id: "all", label: "Whole course" },
  { id: "dates", label: "Dates" },
  { id: "sections", label: "Sections" },
];

function shift(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function isoDay(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Older browsers or no permission: select a hidden textarea and copy.
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

export default function Prompt({ course }: { course?: number }) {
  const { data, error } = useLoad(() => request<Options>("/api/prompt/options"), []);
  if (!data) return <Status error={error} loading />;
  if (!data.courses.length) {
    return (
      <>
        <h1>Prompt builder</h1>
        <p className="empty">No courses yet. Run a sync after connecting Moodle.</p>
      </>
    );
  }
  return <Form options={data} initialCourse={course} />;
}

function Form({ options, initialCourse }: { options: Options; initialCourse?: number }) {
  const first = options.courses.find((c) => c.id === initialCourse) ?? options.courses[0];
  const [courses, setCourses] = useState<number[]>([first.id]);
  const [period, setPeriod] = useState<Period>("2months");
  const [from, setFrom] = useState(shift(options.today, -61));
  const [to, setTo] = useState(options.today);
  const [secFrom, setSecFrom] = useState<number | "">("");
  const [secTo, setSecTo] = useState<number | "">("");
  const [goal, setGoal] = useState(options.goals[0]?.id ?? "");
  const [topic, setTopic] = useState("");
  const [depth, setDepth] = useState("standard");
  const [language, setLanguage] = useState("course");
  const [timeMode, setTimeMode] = useState<TimeMode>("daily");
  const [hoursTotal, setHoursTotal] = useState(6);
  const [hoursPerDay, setHoursPerDay] = useState(2);
  const [days, setDays] = useState(7);
  const [deadlines, setDeadlines] = useState(true);
  const [completion, setCompletion] = useState(true);
  const [save, setSave] = useState(true);
  const [built, setBuilt] = useState<Built | null>(null);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);

  const selected = options.courses.filter((c) => courses.includes(c.id));
  const goalInfo = options.goals.find((g) => g.id === goal);
  const single = selected.length === 1 ? selected[0] : null;
  const nextDeadline = useMemo(() => {
    const due = selected.map((c) => c.next_deadline).filter((d): d is number => d != null);
    return due.length ? Math.min(...due) : null;
  }, [selected]);

  // Quick picks fill in the dates, so you always see (and can adjust) the real period.
  function pick(p: Period) {
    setPeriod(p);
    if (p === "2months") {
      setFrom(shift(options.today, -61));
      setTo(options.today);
    } else if (p === "4weeks") {
      setFrom(shift(options.today, -28));
      setTo(options.today);
    } else if (p === "deadline") {
      setFrom("");
      setTo(nextDeadline ? isoDay(nextDeadline) : options.today);
    } else if (p === "all" || p === "sections") {
      setFrom("");
      setTo("");
    }
  }

  const body = useMemo(() => {
    const useSections = period === "sections" && single;
    return {
      course_ids: courses,
      goal,
      from: period === "all" || period === "sections" ? null : from || null,
      to: period === "all" || period === "sections" ? null : to || null,
      section_from: useSections && secFrom !== "" ? secFrom : null,
      section_to: useSections && secTo !== "" ? secTo : null,
      topic: goalInfo?.topic === "none" ? "" : topic,
      depth,
      language,
      hours_total: timeMode === "total" ? hoursTotal : null,
      hours_per_day: timeMode === "daily" ? hoursPerDay : null,
      days: timeMode === "daily" ? days : null,
      include_deadlines: deadlines,
      include_completion: completion,
      save_results: save,
    };
  }, [courses, goal, period, from, to, secFrom, secTo, single, topic, goalInfo, depth, language,
      timeMode, hoursTotal, hoursPerDay, days, deadlines, completion, save]);

  // Rebuild the preview shortly after each change.
  useEffect(() => {
    if (!courses.length) {
      setBuilt(null);
      setBuildError("Choose at least one course.");
      return;
    }
    const id = ++seq.current;
    setBusy(true);
    const timer = window.setTimeout(() => {
      request<Built>("/api/prompt/build", { method: "POST", body: JSON.stringify(body) })
        .then((r) => {
          if (id !== seq.current) return;
          setBuilt(r);
          setBuildError(null);
        })
        .catch((e: ApiError) => {
          if (id !== seq.current) return;
          setBuilt(null);
          setBuildError(e.message);
        })
        .finally(() => id === seq.current && setBusy(false));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [body, courses.length]);

  function toggleCourse(id: number) {
    setCourses((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]));
  }

  return (
    <div className="builder">
      <div className="builder-form">
        <h1>Prompt builder</h1>
        <p className="muted small">
          Pick a course, a period and a goal, then copy the prompt into Claude (with the Study Companion
          connector on). Claude reads only the material the prompt names.
        </p>

        <fieldset className="field">
          <legend>Course</legend>
          <div className="choices">
            {options.courses.map((c) => (
              <label key={c.id} className="choice">
                <input type="checkbox" checked={courses.includes(c.id)} onChange={() => toggleCourse(c.id)} />
                <span>
                  {c.fullname}
                  {c.lang && <span className="tag">{c.lang}</span>}
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className="field">
          <legend>Period</legend>
          <div className="segmented wrap">
            {PERIODS.filter((p) => p.id !== "sections" || single).map((p) => (
              <button key={p.id} type="button" aria-pressed={period === p.id} onClick={() => pick(p.id)}>
                {p.label}
              </button>
            ))}
          </div>
          {period === "deadline" && (
            <p className="muted small">
              {nextDeadline ? `Next deadline: ${when(nextDeadline)}` : "No upcoming deadline: using today."}
            </p>
          )}
          {period !== "all" && period !== "sections" && (
            <div className="inline">
              <label>
                From
                <input type="date" value={from} max={to || undefined}
                  onChange={(e) => { setFrom(e.target.value); setPeriod("dates"); }} />
              </label>
              <label>
                To
                <input type="date" value={to} min={from || undefined}
                  onChange={(e) => { setTo(e.target.value); setPeriod("dates"); }} />
              </label>
            </div>
          )}
          {period === "sections" && single && (
            <div className="inline">
              <label>
                From section
                <select value={secFrom} onChange={(e) => setSecFrom(e.target.value === "" ? "" : Number(e.target.value))}>
                  <option value="">First</option>
                  {single.sections.map((s) => (
                    <option key={s.id} value={s.number}>{s.number}. {s.name}</option>
                  ))}
                </select>
              </label>
              <label>
                To section
                <select value={secTo} onChange={(e) => setSecTo(e.target.value === "" ? "" : Number(e.target.value))}>
                  <option value="">Last</option>
                  {single.sections.map((s) => (
                    <option key={s.id} value={s.number}>{s.number}. {s.name}</option>
                  ))}
                </select>
              </label>
            </div>
          )}
        </fieldset>

        <fieldset className="field">
          <legend>Goal</legend>
          <select value={goal} onChange={(e) => setGoal(e.target.value)} className="full">
            {options.goals.map((g) => (
              <option key={g.id} value={g.id}>{g.title}</option>
            ))}
          </select>
          {goalInfo && <p className="muted small">{goalInfo.description}</p>}
          {goalInfo && goalInfo.topic !== "none" && (
            <label className="block">
              {goalInfo.topic === "required" ? "Topic" : "Topic (optional)"}
              <input type="text" value={topic} maxLength={200} className="full"
                placeholder={goal === "assignment" ? "Assignment name" : "e.g. eigenvalues"}
                onChange={(e) => setTopic(e.target.value)} />
            </label>
          )}
        </fieldset>

        <fieldset className="field">
          <legend>Depth</legend>
          <div className="segmented">
            {options.depths.map((d) => (
              <button key={d.id} type="button" aria-pressed={depth === d.id} onClick={() => setDepth(d.id)}>
                {d.title}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="field">
          <legend>Time available</legend>
          <div className="segmented">
            <button type="button" aria-pressed={timeMode === "daily"} onClick={() => setTimeMode("daily")}>Per day</button>
            <button type="button" aria-pressed={timeMode === "total"} onClick={() => setTimeMode("total")}>Total</button>
            <button type="button" aria-pressed={timeMode === "none"} onClick={() => setTimeMode("none")}>Not set</button>
          </div>
          {timeMode === "daily" && (
            <div className="inline">
              <label>
                Hours per day
                <input type="number" min={0.5} max={24} step={0.5} value={hoursPerDay}
                  onChange={(e) => setHoursPerDay(Number(e.target.value))} />
              </label>
              <label>
                Days
                <input type="number" min={1} max={365} value={days} onChange={(e) => setDays(Number(e.target.value))} />
              </label>
            </div>
          )}
          {timeMode === "total" && (
            <div className="inline">
              <label>
                Hours in total
                <input type="number" min={0.5} max={1000} step={0.5} value={hoursTotal}
                  onChange={(e) => setHoursTotal(Number(e.target.value))} />
              </label>
            </div>
          )}
        </fieldset>

        <fieldset className="field">
          <legend>Language and options</legend>
          <label className="block">
            Answers in
            <select value={language} onChange={(e) => setLanguage(e.target.value)} className="full">
              <option value="course">The course's language</option>
              {options.languages.map((l) => (
                <option key={l.id} value={l.id}>{l.title}</option>
              ))}
            </select>
          </label>
          <label className="choice">
            <input type="checkbox" checked={deadlines} onChange={(e) => setDeadlines(e.target.checked)} />
            <span>Include upcoming deadlines</span>
          </label>
          <label className="choice">
            <input type="checkbox" checked={completion} onChange={(e) => setCompletion(e.target.checked)} />
            <span>Use completion status (skip what is done)</span>
          </label>
          <label className="choice">
            <input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} />
            <span>Save results to the app (summaries, flashcards, quiz scores)</span>
          </label>
        </fieldset>
      </div>

      <div className="builder-result" aria-live="polite">
        <Result built={built} error={buildError} busy={busy} />
      </div>
    </div>
  );
}

function Result({ built, error, busy }: { built: Built | null; error: string | null; busy: boolean }) {
  if (error) return <p className="alert" role="alert">{error}</p>;
  if (!built) return <p className="loading">{busy ? "Building…" : ""}</p>;
  const s = built.summary;
  return (
    <>
      <h2>Preview</h2>
      <p className={busy ? "muted" : undefined}>
        {s.sections} section{s.sections === 1 ? "" : "s"} · {s.files} file{s.files === 1 ? "" : "s"}
        {" "}({s.readable_files} with text) · about {s.pages} page{s.pages === 1 ? "" : "s"}
        {s.prompts > 1 && <> · split into {s.prompts} prompts to stay within Claude's limits</>}
      </p>
      {built.courses.filter((c) => c.note).map((c) => (
        <p key={c.id} className="banner warn small">{c.fullname}: {c.note}</p>
      ))}
      {built.prompts.map((p, i) => (
        <PromptCard key={i} title={p.title} text={p.text} />
      ))}
      <p className="muted small">
        Paste it in a new chat on <a href="https://claude.ai/new" target="_blank" rel="noopener noreferrer">claude.ai ↗</a> or
        in the Claude app, with the Study Companion connector enabled.
      </p>
    </>
  );
}

function PromptCard({ title, text }: { title: string; text: string }) {
  const [copied, setCopied] = useState<"" | "ok" | "fail">("");
  useEffect(() => setCopied(""), [text]);
  return (
    <section className="prompt-card">
      <div className="prompt-head">
        <strong>{title}</strong>
        <button type="button" className="btn small"
          onClick={() => copyText(text).then((ok) => setCopied(ok ? "ok" : "fail"))}>
          {copied === "ok" ? "Copied ✓" : "Copy"}
        </button>
      </div>
      {copied === "fail" && <p className="alert small">Copy failed: select the text and copy it by hand.</p>}
      <pre className="prompt-text">{text}</pre>
    </section>
  );
}
