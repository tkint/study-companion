import { lazy, Suspense } from "react";
import { href, useRoute, type Route } from "./router";
import Dashboard from "./pages/Dashboard";
import Courses from "./pages/Courses";
import Course from "./pages/Course";
import ThemeSwitch from "./components/ThemeSwitch";

// Heavy parts (FullCalendar, pdf.js) load only when opened.
const Calendar = lazy(() => import("./pages/Calendar"));
const FileViewer = lazy(() => import("./pages/FileViewer"));
const Prompt = lazy(() => import("./pages/Prompt"));

function Page({ route }: { route: Route }) {
  switch (route.name) {
    case "courses":
      return <Courses />;
    case "course":
      return <Course id={route.id} />;
    case "calendar":
      return <Calendar />;
    case "prompt":
      return <Prompt course={route.course} />;
    case "file":
      return <FileViewer id={route.id} course={route.course} />;
    default:
      return <Dashboard />;
  }
}

const TABS = [
  { route: "dashboard", label: "Today", href: href.dashboard, icon: "M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10" },
  { route: "courses", label: "Courses", href: href.courses, icon: "M4 5h7a3 3 0 013 3v12a2 2 0 00-2-2H4zM20 5h-5a3 3 0 00-3 3" },
  { route: "calendar", label: "Calendar", href: href.calendar, icon: "M4 6h16v14H4zM4 10h16M9 3v5M15 3v5" },
  { route: "prompt", label: "Prompt", href: href.prompt(), icon: "M4 5h16v11H9l-5 4zM8 9h8M8 12h5" },
] as const;

export default function App() {
  const route = useRoute();
  const active = route.name === "course" ? "courses" : route.name;
  if (route.name === "file") {
    return (
      <Suspense fallback={<p className="loading">Loading viewer…</p>}>
        <Page route={route} />
      </Suspense>
    );
  }
  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href={href.dashboard}>
          <img src="/favicon.svg" alt="" width={28} height={28} />
          <span>Study Companion</span>
        </a>
        <nav className="tabs" aria-label="Main">
          {TABS.map((t) => (
            <a key={t.route} href={t.href} aria-current={active === t.route ? "page" : undefined}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d={t.icon} /></svg>
              <span>{t.label}</span>
            </a>
          ))}
          <a href="/settings">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="3" />
              <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" />
            </svg>
            <span>Settings</span>
          </a>
        </nav>
        <ThemeSwitch />
      </header>
      <main className="content">
        <Suspense fallback={<p className="loading">Loading…</p>}>
          <Page route={route} />
        </Suspense>
      </main>
    </div>
  );
}
