import styled from "styled-components";
import type { Deadline, PlanTask, ScheduleBlock, ScheduleReading, ScheduleSession } from "../api";
import { courseColor, sourceLabel } from "../format";
import { minutes } from "../pages/Plan";
import { href, type PromptPrefill } from "../router";
import { Button, Fold, List, Modal, Muted, Row, Swatch } from "../ui";
import { DeadlineItem } from "./DeadlineList";
import { TaskList, TaskRow } from "./DayTasks";
import { BlockRow, clock, ReadingDetails } from "./ScheduleBlock";

// The details of a calendar entry (a course's study session, a long reading or a deadline):
// what it is, its tasks with their ticks, links to it in the app and at the source, and a
// shortcut to the prompt builder filled in for that session.

export type Selected = { deadline?: Deadline; session?: ScheduleSession; reading?: ScheduleReading };

interface Links {
  /** The section (or course) in the app. */
  app?: { href: string; label: string };
  /** The page at the source site (the section, or the assignment or quiz). */
  source?: string;
  /** The prompt builder, filled in for this session. */
  prompt?: string;
}

/** A section's page at the source: ``course/view.php`` with its anchor works on every
 * Moodle version (``course/section.php`` only on recent ones). */
export function sectionSource(site: string, course: number, section?: number | null): string {
  if (!site) return "";
  return `${site}/course/view.php?id=${course}${section != null ? `#section-${section}` : ""}`;
}

function http(url: string | undefined | null): string | undefined {
  return url && /^https?:\/\//i.test(url) ? url : undefined;
}

/** The goal for a task: an assignment to understand, a quiz to prepare, or plain study. */
function taskGoal(kind: string | null | undefined): string {
  return kind === "assign" ? "assignment" : kind === "quiz" ? "exam_prep" : "study_session";
}

function sessionLinks(g: ScheduleSession, site: string): Links {
  const course = g.course_id;
  if (course == null) {
    return g.kind === "flashcards" ? { app: { href: href.study({ due: true }), label: "Review cards" } } : {};
  }
  const sections = g.blocks.filter((b) => b.section_number != null);
  const first: ScheduleBlock | undefined = sections[0];
  const task = g.blocks.find((b) => b.item_kind && b.item_kind !== "section");
  const nums = sections.map((b) => b.section_number as number);
  const prefill: PromptPrefill = { minutes: g.minutes };
  if (!sections.length && task) {
    prefill.goal = taskGoal(task.item_kind);
    prefill.topic = task.needed_for || task.title;
  } else {
    prefill.goal = "study_session";
    const titles = [...new Set(sections.map((b) => b.title))];
    if (titles.length === 1) prefill.topic = titles[0];
    if (nums.length) {
      prefill.sectionFrom = Math.min(...nums);
      prefill.sectionTo = Math.max(...nums);
    }
  }
  return {
    app: first
      ? { href: href.course(course, first.section_id ?? undefined), label: "Open section" }
      : { href: href.course(course), label: "Open course" },
    source: http(task?.url) ?? http(sectionSource(site, course, first?.section_number)),
    prompt: href.prompt(course, prefill),
  };
}

function readingLinks(r: ScheduleReading, site: string): Links {
  if (r.course_id == null) return {};
  return {
    app: { href: href.course(r.course_id, r.section_id ?? undefined), label: r.section_id ? "Open section" : "Open course" },
    source: http(sectionSource(site, r.course_id, r.section_number)),
    prompt: href.prompt(r.course_id, {
      goal: "study_session", topic: r.title,
      sectionFrom: r.section_number ?? undefined, sectionTo: r.section_number ?? undefined,
    }),
  };
}

function deadlineLinks(d: Deadline): Links {
  if (d.course_id == null) return {};
  // The deadline's own row has its source link and the Done button.
  return {
    app: { href: href.course(d.course_id), label: "Open course" },
    prompt: href.prompt(d.course_id, { goal: taskGoal(d.source), topic: d.name }),
  };
}

export function eventLinks(sel: Selected, site: string): Links {
  if (sel.session) return sessionLinks(sel.session, site);
  if (sel.reading) return readingLinks(sel.reading, site);
  if (sel.deadline) return deadlineLinks(sel.deadline);
  return {};
}

const Head = styled.header`
  display: flex;
  gap: 12px;
  min-width: 0;
  & h2 { margin: 0; overflow-wrap: anywhere; }
`;

const Sub = styled(Muted)`
  display: block;
  margin-top: 2px;
`;

const TasksHead = styled.h3`
  margin: 4px 0;
  font-size: ${({ theme }) => theme.fontSizes.md};
`;

const Actions = styled(Row)`
  gap: 8px;
  ${({ theme }) => theme.media.phone} {
    & > * { flex: 1 1 auto; justify-content: center; }
  }
`;

function longDay(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

function header(sel: Selected, timeZone: string): { title: string; sub: string; color: string } {
  if (sel.session) {
    const g = sel.session;
    return {
      title: g.label,
      sub: `${longDay(g.start)} · ${clock(g.start, timeZone)}–${clock(g.end, timeZone)} · ${minutes(g.minutes)}`,
      color: g.color,
    };
  }
  if (sel.reading) {
    const r = sel.reading;
    return { title: r.label, sub: `${r.pages} pages at your own pace`, color: r.color };
  }
  const d = sel.deadline as Deadline;
  return {
    title: d.name,
    sub: [sourceLabel(d.source), d.course_shortname || d.course_name].filter(Boolean).join(" · "),
    color: courseColor(d.course_id),
  };
}

export function EventDialog({ selected, site, timeZone, onClose, onDeadline, tasks = [], done, onTick }: {
  selected: Selected | null;
  site: string;
  timeZone: string;
  onClose: () => void;
  onDeadline: (d: Deadline) => void;
  /** The session's tasks (its task_keys on its day), with their ticks. */
  tasks?: PlanTask[];
  done?: (t: PlanTask) => boolean;
  onTick?: (t: PlanTask, done: boolean) => void;
}) {
  const open = !!(selected && (selected.session || selected.reading || selected.deadline));
  if (!open || !selected) return null;
  const head = header(selected, timeZone);
  const links = eventLinks(selected, site);
  return (
    <Modal open onClose={onClose} label={head.title} medium>
      <Head>
        <Swatch style={{ background: head.color }} aria-hidden="true" />
        <div>
          <h2>{head.title}</h2>
          <Sub $small>{head.sub}</Sub>
        </div>
      </Head>
      {(links.prompt || links.app || links.source) && (
        <Actions>
          {links.prompt && (
            <Button as="a" $variant="primary" $size="sm" href={links.prompt}
              title="Open the prompt builder filled in for this session">
              ✨ Build the session prompt
            </Button>
          )}
          {links.app && <Button as="a" $variant="soft" $size="sm" href={links.app.href}>{links.app.label}</Button>}
          {links.source && (
            <Button as="a" $variant="outline" $size="sm" href={links.source} target="_blank" rel="noopener noreferrer">
              At the source ↗
            </Button>
          )}
        </Actions>
      )}
      {selected.reading && <ReadingDetails reading={selected.reading} />}
      {selected.deadline && (
        <List $animate={false}>
          <DeadlineItem d={selected.deadline} onChange={onDeadline} showCourse={false} />
        </List>
      )}
      {selected.session && tasks.length > 0 && done && onTick && (
        <section aria-label="Tasks of this session">
          <TasksHead>Tasks</TasksHead>
          <TaskList>
            {tasks.map((t) => <TaskRow key={t.key} task={t} done={done(t)} onTick={onTick} timeZone={timeZone} />)}
          </TaskList>
        </section>
      )}
      {selected.session && (
        <Fold>
          <summary>Planned blocks</summary>
          <List $animate={false}>
            {selected.session.blocks.map((b: ScheduleBlock) => <BlockRow key={b.start} block={b} timeZone={timeZone} />)}
          </List>
        </Fold>
      )}
      <Button $variant="ghost" $block onClick={onClose}>Close</Button>
    </Modal>
  );
}
