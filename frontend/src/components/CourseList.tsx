import { useMemo, useState } from "react";
import type { CourseSummary } from "../api";
import { href } from "../router";
import { Progress } from "./common";
import { CourseCover } from "./CourseCover";

// Case- and accent-insensitive: "algebre" finds "Algèbre linéaire".
export function normalise(text: string): string {
  return text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

export function matches(c: CourseSummary, query: string): boolean {
  const hay = normalise(`${c.fullname} ${c.shortname}`);
  return normalise(query).split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

export function CourseSearch({ value, onChange, autoFocus }: { value: string; onChange: (v: string) => void; autoFocus?: boolean }) {
  return (
    <label className="search">
      <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>
      <input type="search" placeholder="Search courses" aria-label="Search courses" value={value}
        onChange={(e) => onChange(e.target.value)} autoFocus={autoFocus} enterKeyHint="search" />
    </label>
  );
}

export function CourseList({ courses, search = true }: { courses: CourseSummary[]; search?: boolean }) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => courses.filter((c) => matches(c, query)), [courses, query]);
  if (!courses.length) return <p className="empty">No courses yet. Run a sync after connecting your source site.</p>;
  return (
    <>
      {search && <CourseSearch value={query} onChange={setQuery} />}
      {!shown.length && <p className="empty">No course matches “{query}”.</p>}
      <ul className="course-list">
        {shown.map((c) => (
          <li key={c.id}>
            <a className="course-row" href={href.course(c.id)}>
              <CourseCover id={c.id} shortname={c.shortname} fullname={c.fullname} imageUrl={c.image_url} variant="thumb" />
              <div>
                <div className="course-name">{c.fullname}</div>
                <div className="course-meta">
                  <span>{c.shortname}</span>
                  {c.overdue > 0 && <span>{c.overdue} to catch up</span>}
                  {c.upcoming > 0 && <span>{c.upcoming} upcoming</span>}
                </div>
              </div>
              <div className="course-progress">
                {c.progress != null ? (
                  <>
                    <Progress value={c.progress} />
                    {Math.round(c.progress)}% complete
                    {c.activities_tracked > 0 && ` · ${c.activities_done}/${c.activities_tracked} activities`}
                  </>
                ) : (
                  "No completion tracking"
                )}
              </div>
            </a>
          </li>
        ))}
      </ul>
    </>
  );
}
