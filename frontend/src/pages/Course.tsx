import { useState } from "react";
import { api, fileUrl, type CourseDetail, type Deadline, type FileInfo, type ModuleInfo } from "../api";
import { Progress, Status, useLoad } from "../components/common";
import { DeadlineList } from "../components/DeadlineList";
import { size } from "../format";
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

function FileRow({ f, courseId, moduleUrl }: { f: FileInfo; courseId: number; moduleUrl: string }) {
  const label = (
    <>
      <span className="file-name">{f.filename}</span>
      <span className="muted"> {size(f.filesize)}</span>
    </>
  );
  if (!f.available) {
    return (
      <li className="file unavailable">
        {label}
        <span className="muted"> · {FILE_STATUS[f.status] ?? f.status}</span>
        {moduleUrl && (
          <a href={moduleUrl} target="_blank" rel="noopener noreferrer"> · open in Moodle ↗</a>
        )}
      </li>
    );
  }
  return (
    <li className="file">
      {isPdf(f) ? (
        <a href={href.file(f.id, courseId)}>{label}</a>
      ) : (
        <a href={fileUrl(f)} target="_blank" rel="noopener">{label}</a>
      )}
      <a className="file-dl" href={fileUrl(f, true)} aria-label={`Download ${f.filename}`} title="Download">
        ⤓
      </a>
    </li>
  );
}

function ModuleRow({ m, courseId }: { m: ModuleInfo; courseId: number }) {
  const done = m.completion_state === 1 || m.completion_state === 2;
  const [expanded, setExpanded] = useState(false);
  const long = m.description.length > 280;
  return (
    <li className={`module${m.visible ? "" : " hidden"}`}>
      <div className="module-head">
        <span className="tag">{MOD_LABELS[m.modname] ?? m.modname}</span>
        <span className="module-name">{m.name}</span>
        {done && <span className="check" title="Completed in Moodle">✓</span>}
        {m.url && (
          <a className="module-link" href={m.url} target="_blank" rel="noopener noreferrer">
            Moodle ↗
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
      {m.files.length > 0 && (
        <ul className="files">
          {m.files.map((f) => (
            <FileRow key={f.id} f={f} courseId={courseId} moduleUrl={m.url} />
          ))}
        </ul>
      )}
    </li>
  );
}

function Deadlines({ course, onChange }: { course: CourseDetail; onChange: (d: Deadline) => void }) {
  const now = Date.now() / 1000;
  const open = course.deadlines.filter((d) => d.due_at >= now || !d.done);
  const past = course.deadlines.filter((d) => d.due_at < now && d.done);
  return (
    <section>
      <h2>Deadlines</h2>
      <DeadlineList items={open} empty="No open deadlines." onChange={onChange} showCourse={false} />
      {past.length > 0 && (
        <details className="past">
          <summary>{past.length} done</summary>
          <DeadlineList items={past} empty="" onChange={onChange} showCourse={false} />
        </details>
      )}
    </section>
  );
}

export default function Course({ id }: { id: number }) {
  const { data, error, setData } = useLoad(() => api.course(id), [id]);
  if (!data) return <Status error={error} loading />;
  const onChange = (d: Deadline) =>
    setData({ ...data, deadlines: data.deadlines.map((x) => (x.id === d.id ? d : x)) });
  const sections = data.sections.filter((s) => s.modules.length || s.summary);
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
      <section>
        <h2>Sections</h2>
        {!sections.length && <p className="empty">No content synced yet.</p>}
        {sections.map((s, i) => (
          <details key={s.id} className={`section${s.visible ? "" : " hidden"}`} open={i < 2}>
            <summary>
              <span>{s.name}</span>
              <span className="muted"> {s.modules.length}</span>
            </summary>
            {s.summary && <div className="text">{s.summary}</div>}
            <ul className="modules">
              {s.modules.map((m) => (
                <ModuleRow key={m.id} m={m} courseId={data.id} />
              ))}
            </ul>
          </details>
        ))}
      </section>
    </>
  );
}
