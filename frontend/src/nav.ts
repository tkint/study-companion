import { href, type Route } from "./router";

// One map of the app: the main sections (tabs) and the pages inside each. The tab bar, the
// section menu under it, the page title and the tour all read from here, so a new page only
// needs a line below to be findable.

export type SectionId = "dashboard" | "courses" | "study" | "calendar" | "prompt";

export interface NavPage {
  route: Route["name"];
  label: string;
  href: string;
  /** One line on what the page is for (section menu tooltip, tour). */
  hint: string;
}

export interface NavSection {
  id: SectionId;
  label: string;
  /** Shorter label for the phone tab bar. */
  short: string;
  icon: string;
  pages: NavPage[];
  /** Routes that live in this section without a menu entry (detail pages). */
  also?: Route["name"][];
}

export const SECTIONS: NavSection[] = [
  {
    id: "dashboard",
    label: "Today",
    short: "Today",
    icon: "M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10",
    pages: [
      { route: "dashboard", label: "Overview", href: href.dashboard, hint: "Today's plan, what's coming up and your week" },
      { route: "plan", label: "Catch-up plan", href: href.plan, hint: "The work ahead, ordered by deadline, day by day" },
      { route: "schedule", label: "Schedule", href: href.schedule, hint: "The plan with times, around your commitments, with .ics export" },
    ],
  },
  {
    id: "courses",
    label: "Courses",
    short: "Courses",
    icon: "M4 5h7a3 3 0 013 3v12a2 2 0 00-2-2H4zM20 5h-5a3 3 0 00-3 3",
    pages: [{ route: "courses", label: "All courses", href: href.courses, hint: "Every course, its sections, files and deadlines" }],
    also: ["course", "file"],
  },
  {
    id: "study",
    label: "Study",
    short: "Study",
    icon: "M4 7l8-4 8 4-8 4zM8 9v5c0 1.5 2 3 4 3s4-1.5 4-3V9M20 7v6",
    pages: [
      { route: "study", label: "Flashcards", href: href.study(), hint: "Review the cards your AI assistant saved, with spaced repetition" },
      { route: "time", label: "Study time", href: href.time, hint: "A timer, your daily goal and your streak" },
    ],
  },
  {
    id: "calendar",
    label: "Calendar",
    short: "Calendar",
    icon: "M4 6h16v14H4zM4 10h16M9 3v5M15 3v5",
    pages: [{ route: "calendar", label: "Calendar", href: href.calendar, hint: "Deadlines by month, week or list, and phone reminders" }],
  },
  {
    id: "prompt",
    label: "Ask AI",
    short: "AI",
    icon: "M4 5h16v11H9l-5 4zM8 9h8M8 12h5",
    pages: [
      { route: "prompt", label: "Prompt builder", href: href.prompt(), hint: "Build a prompt to paste into your AI assistant with the connector" },
      { route: "templates", label: "Templates", href: href.templates(), hint: "Edit the text behind each prompt goal" },
    ],
  },
];

export function sectionOf(route: Route["name"]): NavSection {
  return SECTIONS.find((s) => s.pages.some((p) => p.route === route) || s.also?.includes(route)) ?? SECTIONS[0];
}

export function pageOf(route: Route["name"]): NavPage | undefined {
  return sectionOf(route).pages.find((p) => p.route === route);
}

const DETAIL_TITLES: Partial<Record<Route["name"], string>> = { course: "Course", file: "File" };

/** "Catch-up plan · Today · Study Companion" for the browser tab and the app switcher. */
export function documentTitle(route: Route): string {
  const section = sectionOf(route.name);
  const page = pageOf(route.name)?.label ?? DETAIL_TITLES[route.name];
  const parts = [page, section.label].filter((x, i, a) => x && a.indexOf(x) === i);
  if (route.name === "dashboard") parts.splice(0, parts.length, "Today");
  return [...parts, "Study Companion"].join(" · ");
}
