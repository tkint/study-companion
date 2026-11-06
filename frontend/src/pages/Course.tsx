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
import styled from "styled-components";
import { Status, useLoad } from "../components/common";
import { celebrate } from "../components/Confetti";
import { CourseCover } from "../components/CourseCover";
import { DeadlineList } from "../components/DeadlineList";
import { PrefsMenu, PrefTags } from "../components/Prefs";
import { Markdown } from "../components/Markdown";
import { QuizResults } from "../components/QuizResults";
import { fromNow, size } from "../format";
import { href } from "../router";
import {
  Badge, Banner, Button, Check, Crumbs, DetailsCard, Empty, Lead, ProgressBar, Row, TextButton, Toggles,
} from "../ui";

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

const Files = styled.ul`
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: grid;
  gap: 4px;
`;

const File = styled.li<{ $unavailable?: boolean }>`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-height: 42px;
  padding: 6px 6px 6px 12px;
  border-radius: ${({ theme }) => theme.radii.sm};
  background: ${({ theme }) => theme.colors.surfaceSunken};
  font-size: ${({ theme }) => theme.fontSizes.md};
  color: ${({ theme, $unavailable }) => ($unavailable ? theme.colors.textMuted : "inherit")};
  & > a:first-child { flex: 1; min-width: 0; overflow-wrap: anywhere; font-weight: 600; }
`;

const Size = styled.span`
  font-weight: 400;
  color: ${({ theme }) => theme.colors.textMuted};
`;

const Modules = styled.ul`
  list-style: none;
  margin: 0;
  padding: 0;
`;

const Module = styled.li<{ $hidden?: boolean }>`
  padding: 12px 0;
  border-bottom: 1px solid ${({ theme }) => theme.colors.border};
  opacity: ${({ $hidden }) => ($hidden ? 0.65 : 1)};
  &:last-child { border-bottom: 0; }
`;

const ModuleHead = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  & > a { font-size: ${({ theme }) => theme.fontSizes.sm}; white-space: nowrap; }
`;

const ModuleName = styled.span`
  flex: 1 1 160px;
  font-weight: 650;
  overflow-wrap: anywhere;
`;

const Done = styled.span`
  color: ${({ theme }) => theme.colors.successText};
  font-weight: 800;
`;

const Text = styled.div<{ $clamp?: boolean }>`
  margin: 4px 0 8px;
  font-size: ${({ theme }) => theme.fontSizes.md};
  white-space: pre-line;
  overflow-wrap: anywhere;
  ${({ $clamp }) => $clamp && "display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden;"}
  & > button { margin-left: 6px; }
`;

const Note = styled.div`
  margin: 8px 0 12px;
  padding: 12px 16px;
  border-radius: ${({ theme }) => theme.radii.md};
  border: 1px solid color-mix(in srgb, ${({ theme }) => theme.colors.primary} 30%, ${({ theme }) => theme.colors.border});
  background: color-mix(in srgb, ${({ theme }) => theme.colors.primarySoft} 60%, ${({ theme }) => theme.colors.surface});
`;

const NoteHead = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  & > strong { flex: 1 1 160px; overflow-wrap: anywhere; }
`;

const Fade = styled.div`
  max-height: 18rem;
  overflow: hidden;
  -webkit-mask-image: linear-gradient(#000 70%, transparent);
  mask-image: linear-gradient(#000 70%, transparent);
`;

const SectionActions = styled.div`
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 0 14px;
  border-top: 1px solid ${({ theme }) => theme.colors.border};
`;

const Count = styled.span`
  font-weight: 500;
  color: ${({ theme }) => theme.colors.textMuted};
`;

function isImage(f: FileInfo) {
  return f.mimetype.startsWith("image/") || /\.(png|jpe?g|gif|webp|svg)$/i.test(f.filename);
}

function FileRow({ f, courseId, moduleUrl, moduleName }: {
  f: FileInfo; courseId: number; moduleUrl: string; moduleName: string;
}) {
  const label = (
    <>
      <span>{f.page ? (f.title === moduleName ? "Read the page" : f.title) : f.title || f.filename}</span>
      {!f.page && <Size> {size(f.filesize)}</Size>}
    </>
  );
  if (!f.available) {
    return (
      <File $unavailable>
        <span>{label}<Size> · {FILE_STATUS[f.status] ?? f.status}</Size></span>
        {moduleUrl && (
          <a href={moduleUrl} target="_blank" rel="noopener noreferrer">open in source ↗</a>
        )}
      </File>
    );
  }
  return (
    <File>
      {isPdf(f) || f.page ? (
        <a href={href.file(f.id, courseId)}>{label}</a>
      ) : (
        <a href={fileUrl(f)} target="_blank" rel="noopener">{label}</a>
      )}
      {!f.page && (
        <Button as="a" $variant="ghost" $size="sm" href={fileUrl(f, true)} aria-label={`Download ${f.filename}`} title="Download">
          ⤓
        </Button>
      )}
    </File>
  );
}

function ModuleRow({ m, courseId }: { m: ModuleInfo; courseId: number }) {
  const done = m.completion_state === 1 || m.completion_state === 2;
  const [expanded, setExpanded] = useState(false);
  const long = m.description.length > 280;
  // A teacher page shows its images inside it: list the page first, then its other files.
  const hasPage = m.files.some((f) => f.page);
  const files = hasPage
    ? [...m.files.filter((f) => f.page), ...m.files.filter((f) => !f.page && !isImage(f))]
    : m.files;
  return (
    <Module $hidden={!m.visible}>
      <ModuleHead>
        <Badge>{MOD_LABELS[m.modname] ?? m.modname}</Badge>
        <ModuleName>{m.name}</ModuleName>
        {done && <Done title="Completed at the source">✓</Done>}
        {m.url && (
          <a href={m.url} target="_blank" rel="noopener noreferrer">
            Source ↗
          </a>
        )}
      </ModuleHead>
      {m.description && (
        <Text $clamp={long && !expanded}>
          {m.description}
          {long && (
            <TextButton onClick={() => setExpanded(!expanded)}>
              {expanded ? "Show less" : "Show more"}
            </TextButton>
          )}
        </Text>
      )}
      {files.length > 0 && (
        <Files>
          {files.map((f) => (
            <FileRow key={f.id} f={f} courseId={courseId} moduleUrl={m.url} moduleName={m.name} />
          ))}
        </Files>
      )}
    </Module>
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
        <Toggles>
          {pastCount > 0 && (
            <Check><input type="checkbox" checked={showPast} onChange={(e) => setShowPast(e.target.checked)} />
              Show past ({pastCount})</Check>
          )}
          {ignoredCount > 0 && (
            <Check><input type="checkbox" checked={showIgnored} onChange={(e) => setShowIgnored(e.target.checked)} />
              Show ignored ({ignoredCount})</Check>
          )}
        </Toggles>
      )}
      {showPast && past.length > 0 && (
        <>
          <h3>Past</h3>
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
    <Note>
      <NoteHead>
        <Badge $tone="primary">AI</Badge>
        <strong>{note.title || "Summary"}</strong>
        <Count>updated {fromNow(note.updated_at)}</Count>
        <TextButton $danger onClick={onDelete} aria-label="Delete this summary">Delete</TextButton>
      </NoteHead>
      {long && !open ? <Fade><Markdown text={note.markdown} /></Fade> : <Markdown text={note.markdown} />}
      {long && (
        <TextButton onClick={() => setOpen(!open)}>{open ? "Show less" : "Show the whole summary"}</TextButton>
      )}
    </Note>
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
      if (!studied) celebrate(button, 40);
      onStudied(!studied);
    } finally {
      setBusy(false);
    }
  }
  return (
    <SectionActions>
      {counts && counts.questions > 0 && (
        <Button as="a" $variant="primary" $size="sm" href={href.study({ section: section.id, all: counts.due === 0 })}>
          {counts.due > 0 ? `Review ${counts.due} card${counts.due === 1 ? "" : "s"}` : `Practise ${counts.questions} cards`}
        </Button>
      )}
      <Button $size="sm" $variant={studied ? "success" : "outline"} onClick={toggle} disabled={busy} aria-pressed={studied}>
        {studied ? "✓ Studied" : "Mark as studied"}
      </Button>
      <PrefsMenu state={section} label={section.name} save={(p) => api.setSectionPrefs(section.id, p)} onChange={onPrefs} />
    </SectionActions>
  );
}

function StudyPanel({ course, study, onChange }: { course: CourseDetail; study: CourseStudy; onChange: (s: CourseStudy) => void }) {
  return (
    <section>
      <h2>Study</h2>
      <Banner $tone="neutral">
        <span>
          {study.notes.length} summar{study.notes.length === 1 ? "y" : "ies"} · {study.questions_total} question
          {study.questions_total === 1 ? "" : "s"}
          {study.questions_due > 0 && <strong> · {study.questions_due} due</strong>}
        </span>
        <Row $tight $gap="6px">
          {study.questions_total > 0 && (
            <Button as="a" $variant="primary" $size="sm" href={href.study({ course: course.id, all: study.questions_due === 0 })}>
              {study.questions_due > 0 ? "Review due cards" : "Practise all"}
            </Button>
          )}
          <Button as="a" $variant="soft" $size="sm" href={href.prompt(course.id)}>Ask AI</Button>
        </Row>
      </Banner>
      {!study.notes.length && !study.questions_total && (
        <Empty>
          Nothing from your AI assistant yet. Build a prompt with “Save results to the app” on, paste it in your AI assistant, and its
          summaries and questions appear here.
        </Empty>
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
    if (!study || !window.confirm("Delete the AI summary of this section?")) return;
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
      <Crumbs>
        <a href={href.courses}>← Courses</a>
      </Crumbs>
      <CourseCover id={data.id} shortname={data.shortname} fullname={data.fullname} imageUrl={data.image_url} variant="banner" />
      <h1>{data.fullname}</h1>
      <Lead>
        {data.shortname}
        {data.lang && ` · ${data.lang.toUpperCase()}`}
        {!data.enrolled && " · no longer enrolled"}
      </Lead>
      <ProgressBar value={data.progress} size="md" tone="success" label="Course progress" />
      <Deadlines course={data} onChange={onChange} />
      {study && <StudyPanel course={data} study={study} onChange={studyLoad.setData} />}
      <section>
        <h2>Sections</h2>
        {!sections.length && <Empty>No content synced yet.</Empty>}
        {sections.map((s, i) => {
          const note = notes.get(s.id);
          const studied = study?.studied.includes(s.id);
          return (
            <DetailsCard key={s.id} id={`section-${s.id}`} $muted={!s.visible || s.ignored}
              open={i < 2 || s.id === section}>
              <summary>
                <span>{s.name}</span>
                <Count>{s.modules.length}</Count>
                {note && <Badge $tone="primary">notes</Badge>}
                {studied && <Badge $tone="success">studied</Badge>}
                <PrefTags state={s} />
              </summary>
              {note && <AiNote note={note} onDelete={() => deleteNote(note)} />}
              {s.summary && <Text>{s.summary}</Text>}
              <Modules>
                {s.modules.map((m) => (
                  <ModuleRow key={m.id} m={m} courseId={data.id} />
                ))}
              </Modules>
              {study && (
                <SectionStudy section={s} study={study} onStudied={(v) => setStudied(s.id, v)}
                  onPrefs={(st) => setSectionState(s.id, st)} />
              )}
            </DetailsCard>
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
