import { useEffect, useState } from "react";
import {
  api,
  fileUrl,
  type CourseDetail,
  type CourseStudy,
  type Deadline,
  type FileInfo,
  type ItemState,
  type ModuleInfo,
  type SectionInfo,
  type StudyNote,
} from "../api";
import { Progress, Status, useLoad } from "../components/common";
import { celebrate } from "../components/Confetti";
import { DeadlineList } from "../components/DeadlineList";
import { PrefsMenu, PrefTags } from "../components/Prefs";
import { Markdown } from "../components/Markdown";
import { QuizResults } from "../components/QuizResults";
import { fromNow, size } from "../format";
import { href } from "../router";

const MOD_LABELS: Record<string, string> = {
  resource: "File",
  folder: "Folder",
  page: "Page",
  url: "Link",
  assign: "Assignment",
  quiz: "Quiz",
  forum: "Forum",
  label: "Note",
  book: "Book",
  lesson: "Lesson",
  h5pactivity: "H5P",
  scorm: "SCORM",
};

const FILE_STATUS: Record<string, string> = {
  pending: "not downloaded yet",
  skipped_size: "too large to keep on the server",
  external: "hosted elsewhere",
  error: "download failed",
};

function isPdf(f: FileInfo) {
  return f.mimetype === "application/pdf" || f.filename.toLowerCase().endsWith(".pdf");
}

function isImage(f: FileInfo) {
  return f.mimetype.startsWith("image/") || /\.(png|jpe?g|gif|webp|svg)$/i.test(f.filename);
}

function FileRow({ f, courseId, moduleUrl, moduleName }: {
  f: FileInfo; courseId: number; moduleUrl: string; moduleName: string;
}) {
  const label = (
    <>
      <span className="file-name">
        {f.page ? (f.title === moduleName ? "Read the page" : f.title) : f.title || f.filename}
      </span>
      {!f.page && <span className="muted"> {size(f.filesize)}</span>}
    </>
  );
  if (!f.available) {
    return (
      <li className="file unavailable">
        {label}
        <span className="muted"> · {FILE_STATUS[f.status] ?? f.status}</span>
        {moduleUrl && (
          <a href={moduleUrl} target="_blank" rel="noopener noreferrer"> · open in source ↗</a>
        )}
      </li>
    );
  }
  return (
    <li className="file">
      {isPdf(f) || f.page ? (
        <a href={href.file(f.id, courseId)}>{label}</a>
      ) : (
        <a href={fileUrl(f)} target="_blank" rel="noopener">{label}</a>
      )}
      {!f.page && (
        <a className="file-dl" href={fileUrl(f, true)} aria-label={`Download ${f.filename}`} title="Download">
          ⤓
        </a>
      )}
    </li>
  );
}

function ModuleRow({ m, courseId }: { m: ModuleInfo; courseId: number }) {
  const done = m.completion_state === 1 || m.completion_state === 2;
  const [expanded, setExpanded] = useState(false);
  const long = m.description.length > 280;
  // Images of a teacher page are shown inside the page; list only the page and its other files.
  const hasPage = m.files.some((f) => f.page);
  const files = hasPage
    ? [...m.files.filter((f) => f.page), ...m.files.filter((f) => !f.page && !isImage(f))]
    : m.files;
  return (
    <li className={`module${m.visible ? "" : " hidden"}`}>
      <div className="module-head">
        <span className="tag">{MOD_LABELS[m.modname] ?? m.modname}</span>
        <span className="module-name">{m.name}</span>
        {done && <span className="check" title="Completed at the source">✓</span>}
        {m.url && (
          <a className="module-link" href={m.url} target="_blank" rel="noopener noreferrer">
            Source ↗
          </a>
        )}
      </div>
      {m.description && (
        <div className={`text${long && !expanded ? " clamp" : ""}`}>
          {m.description}
          {long && (
            <button className="link" onClick={() => setExpanded(!expanded)}>
              {expanded ? "Show less" : "Show more"}
            </button>
          )}
        </div>
      )}
      {files.length > 0 && (
        <ul className="files">
          {files.map((f) => (
            <FileRow key={f.id} f={f} courseId={courseId} moduleUrl={m.url} moduleName={m.name} />
          ))}
        </ul>
      )}
    </li>
  );
}

// Only what is ahead by default; the past (and what you chose to ignore) one tap away.
function Deadlines({ course, onChange }: { course: CourseDetail; onChange: (d: Deadline) => void }) {
  const [showPast, setShowPast] = useState(false);
  const [showIgnored, setShowIgnored] = useState(false);
  const now = Date.now() / 1000;
  const visible = course.deadlines.filter((d) => showIgnored || !d.ignored);
  const upcoming = visible.filter((d) => d.due_at >= now);
  const past = visible.filter((d) => d.due_at < now);
  const pastCount = course.deadlines.filter((d) => d.due_at < now && (showIgnored || !d.ignored)).length;
  const ignoredCount = course.deadlines.filter((d) => d.ignored).length;
  return (
    <section>
      <h2>Deadlines</h2>
      <DeadlineList items={upcoming} empty="Nothing coming up." onChange={onChange} showCourse={false} />
      {(pastCount > 0 || ignoredCount > 0) && (
        <div className="view-toggles">
          {pastCount > 0 && (
            <label><input type="checkbox" checked={showPast} onChange={(e) => setShowPast(e.target.checked)} />
              Show past ({pastCount})</label>
          )}
          {ignoredCount > 0 && (
            <label><input type="checkbox" checked={showIgnored} onChange={(e) => setShowIgnored(e.target.checked)} />
              Show ignored ({ignoredCount})</label>
          )}
        </div>
      )}
      {showPast && past.length > 0 && (
        <>
          <h3 className="small muted">Past</h3>
          <DeadlineList items={[...past].reverse()} empty="" onChange={onChange} showCourse={false} />
        </>
      )}
    </section>
  );
}

function AiNote({ note, onDelete }: { note: StudyNote; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const long = note.markdown.length > 900;
  return (
    <div className="ai-note">
      <div className="ai-note-head">
        <span className="tag ai">Claude</span>
        <strong>{note.title || "Summary"}</strong>
        <span className="muted small">updated {fromNow(note.updated_at)}</span>
        <button className="link danger" onClick={onDelete} aria-label="Delete this summary">Delete</button>
      </div>
      <div className={long && !open ? "fade" : undefined}>
        <Markdown text={note.markdown} />
      </div>
      {long && (
        <button className="link" onClick={() => setOpen(!open)}>{open ? "Show less" : "Show the whole summary"}</button>
      )}
    </div>
  );
}

function SectionStudy({ section, study, onStudied, onPrefs }: {
  section: SectionInfo;
  study: CourseStudy;
  onStudied: (studied: boolean) => void;
  onPrefs: (s: ItemState) => void;
}) {
  const [busy, setBusy] = useState(false);
  const studied = study.studied.includes(section.id);
  const counts = study.questions[String(section.id)];
  async function toggle(e: React.MouseEvent<HTMLButtonElement>) {
    const button = e.currentTarget;
    setBusy(true);
    try {
      await api.setStudied(section.id, !studied);
      if (!studied) celebrate(button, 60);
      onStudied(!studied);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="section-study">
      {counts && counts.questions > 0 && (
        <a className="btn btn-primary btn-sm" href={href.study({ section: section.id, all: counts.due === 0 })}>
          {counts.due > 0 ? `Review ${counts.due} card${counts.due === 1 ? "" : "s"}` : `Practise ${counts.questions} cards`}
        </a>
      )}
      <button className={`btn btn-sm ${studied ? "btn-success" : "btn-ghost"}`} onClick={toggle} disabled={busy} aria-pressed={studied}>
        {studied ? "✓ Studied" : "Mark as studied"}
      </button>
      <PrefsMenu state={section} label={section.name} save={(p) => api.setSectionPrefs(section.id, p)} onChange={onPrefs} />
    </div>
  );
}

function StudyPanel({ course, study, onChange }: { course: CourseDetail; study: CourseStudy; onChange: (s: CourseStudy) => void }) {
  return (
    <section>
      <h2>Study</h2>
      <div className="study-bar">
        <span>
          {study.notes.length} summar{study.notes.length === 1 ? "y" : "ies"} · {study.questions_total} question
          {study.questions_total === 1 ? "" : "s"}
          {study.questions_due > 0 && <strong> · {study.questions_due} due</strong>}
        </span>
        <span className="row tight">
          {study.questions_total > 0 && (
            <a className="btn btn-primary btn-sm" href={href.study({ course: course.id, all: study.questions_due === 0 })}>
              {study.questions_due > 0 ? "Review due cards" : "Practise all"}
            </a>
          )}
          <a className="btn btn-sm btn-ghost" href={href.prompt(course.id)}>Ask Claude</a>
        </span>
      </div>
      {!study.notes.length && !study.questions_total && (
        <p className="empty small">
          Nothing from Claude yet. Build a prompt with “Save results to the app” on, paste it in Claude, and its
          summaries and questions appear here.
        </p>
      )}
      <QuizResults results={study.results} onDelete={(id) => onChange({ ...study, results: study.results.filter((r) => r.id !== id) })} />
    </section>
  );
}

export default function Course({ id, section }: { id: number; section?: number }) {
  const { data, error, setData } = useLoad(() => api.course(id), [id]);
  const studyLoad = useLoad(() => api.courseStudy(id), [id]);
  const study = studyLoad.data;
  useEffect(() => {
    if (data && section) document.getElementById(`section-${section}`)?.scrollIntoView({ block: "start" });
  }, [data, section]);
  if (!data) return <Status error={error} loading />;
  const onChange = (d: Deadline) =>
    setData({ ...data, deadlines: data.deadlines.map((x) => (x.id === d.id ? d : x)) });
  const sections = data.sections.filter((s) => s.modules.length || s.summary);
  const notes = new Map((study?.notes ?? []).map((n) => [n.section_id, n]));
  const orphans = (study?.notes ?? []).filter((n) => !sections.some((s) => s.id === n.section_id));

  async function deleteNote(note: StudyNote) {
    if (!study || !window.confirm("Delete Claude's summary of this section?")) return;
    await api.deleteNote(note.id);
    studyLoad.setData({ ...study, notes: study.notes.filter((n) => n.id !== note.id) });
  }
  function setSectionState(sectionId: number, st: ItemState) {
    if (!data) return;
    setData({ ...data, sections: data.sections.map((x) => (x.id === sectionId ? { ...x, ...st, id: x.id } : x)) });
  }
  function setStudied(sectionId: number, studied: boolean) {
    if (!study) return;
    studyLoad.setData({
      ...study,
      studied: studied ? [...study.studied, sectionId] : study.studied.filter((x) => x !== sectionId),
    });
  }

  return (
    <>
      <p className="crumbs">
        <a href={href.courses}>← Courses</a>
      </p>
      <h1>{data.fullname}</h1>
      <p className="muted">
        {data.shortname}
        {data.lang && ` · ${data.lang.toUpperCase()}`}
        {!data.enrolled && " · no longer enrolled"}
      </p>
      {data.progress != null && <Progress value={data.progress} />}
      <Deadlines course={data} onChange={onChange} />
      {study && <StudyPanel course={data} study={study} onChange={studyLoad.setData} />}
      <section>
        <h2>Sections</h2>
        {!sections.length && <p className="empty">No content synced yet.</p>}
        {sections.map((s, i) => {
          const note = notes.get(s.id);
          const studied = study?.studied.includes(s.id);
          return (
            <details key={s.id} id={`section-${s.id}`}
              className={`section${s.visible ? "" : " hidden"}${s.ignored ? " ignored" : ""}`}
              open={i < 2 || s.id === section}>
              <summary>
                <span>{s.name}</span>
                <span className="muted"> {s.modules.length}</span>
                {note && <span className="tag ai">notes</span>}
                {studied && <span className="tag ok">studied</span>}
                <PrefTags state={s} />
              </summary>
              {note && <AiNote note={note} onDelete={() => deleteNote(note)} />}
              {s.summary && <div className="text">{s.summary}</div>}
              <ul className="modules">
                {s.modules.map((m) => (
                  <ModuleRow key={m.id} m={m} courseId={data.id} />
                ))}
              </ul>
              {study && (
                <SectionStudy section={s} study={study} onStudied={(v) => setStudied(s.id, v)}
                  onPrefs={(st) => setSectionState(s.id, st)} />
              )}
            </details>
          );
        })}
        {orphans.length > 0 && (
          <>
            <h2>Notes for sections no longer in the source</h2>
            {orphans.map((n) => <AiNote key={n.id} note={n} onDelete={() => deleteNote(n)} />)}
          </>
        )}
      </section>
    </>
  );
}
