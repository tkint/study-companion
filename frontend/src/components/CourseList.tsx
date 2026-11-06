import { useMemo, useState } from "react";
import styled from "styled-components";
import type { CourseSummary } from "../api";
import { href } from "../router";
import { Card, Empty, List, ProgressBar } from "../ui";

// Case- and accent-insensitive: "algebre" finds "Algèbre linéaire".
export function normalise(text: string): string {
  return text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

export function matches(c: CourseSummary, query: string): boolean {
  const hay = normalise(`${c.fullname} ${c.shortname}`);
  return normalise(query).split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

const Search = styled.label`
  display: block;
  position: relative;
  margin: 0 0 16px;
  svg {
    position: absolute;
    left: 14px;
    top: 50%;
    width: 18px;
    height: 18px;
    transform: translateY(-50%);
    fill: none;
    stroke: ${({ theme }) => theme.colors.textMuted};
    stroke-width: 2;
    stroke-linecap: round;
  }
  input {
    width: 100%;
    min-height: ${({ theme }) => theme.layout.tap};
    padding: 11px 14px 11px 42px;
    font-size: 16px;
    color: ${({ theme }) => theme.colors.textMain};
    background: ${({ theme }) => theme.colors.surface};
    border: 1px solid ${({ theme }) => theme.colors.borderStrong};
    border-radius: ${({ theme }) => theme.radii.pill};
    transition: border-color ${({ theme }) => theme.motion.base}, box-shadow ${({ theme }) => theme.motion.base};
    &:focus {
      outline: none;
      border-color: ${({ theme }) => theme.colors.primary};
      box-shadow: 0 0 0 3px color-mix(in srgb, ${({ theme }) => theme.colors.primary} 25%, transparent);
    }
  }
`;

export function CourseSearch({ value, onChange, autoFocus }: { value: string; onChange: (v: string) => void; autoFocus?: boolean }) {
  return (
    <Search>
      <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>
      <input type="search" placeholder="Search courses" aria-label="Search courses" value={value}
        onChange={(e) => onChange(e.target.value)} autoFocus={autoFocus} enterKeyHint="search" />
    </Search>
  );
}

/** One course per row: name and counts on the left, progress on the right (stacked on a phone). */
export const CourseRow = styled(Card)<{ $stack?: boolean }>`
  display: grid;
  grid-template-columns: ${({ $stack }) => ($stack ? "1fr" : "minmax(0, 1fr) minmax(140px, 220px)")};
  align-items: center;
  gap: 8px 24px;
  ${({ theme }) => theme.media.phone} { grid-template-columns: 1fr; }
`;

export const CourseName = styled.div`
  font-weight: 700;
  overflow-wrap: anywhere;
  a& { display: block; color: ${({ theme }) => theme.colors.textMain}; }
`;

export const CourseMeta = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 2px 12px;
  margin-top: 2px;
  font-size: ${({ theme }) => theme.fontSizes.sm};
  color: ${({ theme }) => theme.colors.textMuted};
`;

const CourseProgress = styled.div<{ $stack?: boolean }>`
  display: grid;
  gap: 6px;
  font-size: ${({ theme }) => theme.fontSizes.sm};
  color: ${({ theme }) => theme.colors.textMuted};
  text-align: ${({ $stack }) => ($stack ? "left" : "right")};
  ${({ theme }) => theme.media.phone} { text-align: left; }
`;

export function CourseList({ courses, search = true, stack = false }: {
  courses: CourseSummary[];
  search?: boolean;
  /** Progress under the name, for a narrow column. */
  stack?: boolean;
}) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => courses.filter((c) => matches(c, query)), [courses, query]);
  if (!courses.length) return <Empty>No courses yet. Run a sync after connecting your source site.</Empty>;
  return (
    <>
      {search && <CourseSearch value={query} onChange={setQuery} />}
      {!shown.length && <Empty>No course matches “{query}”.</Empty>}
      <List>
        {shown.map((c) => (
          <li key={c.id}>
            <CourseRow as="a" href={href.course(c.id)} $interactive $stack={stack}>
              <div>
                <CourseName>{c.fullname}</CourseName>
                <CourseMeta>
                  <span>{c.shortname}</span>
                  {c.overdue > 0 && <span>{c.overdue} to catch up</span>}
                  {c.upcoming > 0 && <span>{c.upcoming} upcoming</span>}
                </CourseMeta>
              </div>
              <CourseProgress $stack={stack}>
                {c.progress != null ? (
                  <>
                    <ProgressBar value={c.progress} tone="success" label={`${c.fullname}: progress`} />
                    <span>
                      {Math.round(c.progress)}% complete
                      {c.activities_tracked > 0 && ` · ${c.activities_done}/${c.activities_tracked} activities`}
                    </span>
                  </>
                ) : (
                  "No completion tracking"
                )}
              </CourseProgress>
            </CourseRow>
          </li>
        ))}
      </List>
    </>
  );
}
