import { lazy, Suspense, useEffect } from "react";
import styled, { css } from "styled-components";
import { href, useRoute, type Route } from "./router";
import Dashboard from "./pages/Dashboard";
import Courses from "./pages/Courses";
import Course from "./pages/Course";
import Plan from "./pages/Plan"; // shares its rows with the dashboard
import ThemeSwitch from "./components/ThemeSwitch";
import { SectionNav } from "./components/SectionNav";
import { startTour, Tour } from "./components/Tour";
import { documentTitle, SECTIONS, sectionOf } from "./nav";
import { hop } from "./styles/motion";
import { Loading } from "./ui";

// Heavy parts (FullCalendar, pdf.js) load only when opened.
const Calendar = lazy(() => import("./pages/Calendar"));
const FileViewer = lazy(() => import("./pages/FileViewer"));
const Prompt = lazy(() => import("./pages/Prompt"));
const Study = lazy(() => import("./pages/Study"));
const Templates = lazy(() => import("./pages/Templates"));
const Time = lazy(() => import("./pages/Time"));


function Page({ route }: { route: Route }) {
  switch (route.name) {
    case "courses":
      return <Courses />;
    case "course":
      return <Course id={route.id} section={route.section} />;
    case "study":
      return <Study course={route.course} section={route.section} all={route.all} due={route.due} />;
    case "plan":
      return <Plan />;
    case "calendar":
      return <Calendar />;
    case "time":
      return <Time />;
    case "prompt":
      return <Prompt course={route.course} />;
    case "templates":
      return <Templates id={route.id} />;
    case "file":
      return <FileViewer id={route.id} course={route.course} />;
    default:
      return <Dashboard />;
  }
}


// ---- shell: top bar on wide screens, bottom tab bar on phones

const TopBar = styled.header`
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: ${({ theme }) => theme.layout.topbar};
  padding: 8px 20px;
  /* Solid, no backdrop-filter: that would make the phone tab bar (position: fixed) stick to
     the top bar instead of the screen. */
  background: ${({ theme }) => theme.colors.surface};
  border-bottom: 1px solid ${({ theme }) => theme.colors.border};
  ${({ theme }) => theme.media.phone} {
    padding: 8px 16px;
    padding-top: max(8px, env(safe-area-inset-top));
  }
`;

const Brand = styled.a`
  display: flex;
  align-items: center;
  gap: 10px;
  color: ${({ theme }) => theme.colors.textMain};
  font-weight: 800;
  letter-spacing: -0.01em;
  white-space: nowrap;
  &:hover { text-decoration: none; }
  @media (max-width: 360px) { span { display: none; } }
  img { transition: transform ${({ theme }) => theme.motion.base} ${({ theme }) => theme.motion.spring}; }
  &:hover img { transform: rotate(-8deg) scale(1.05); }
`;

const Tabs = styled.nav`
  display: flex;
  gap: 4px;
  margin-left: auto;
  ${({ theme }) => theme.media.phone} {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 10;
    margin: 0;
    gap: 0;
    background: ${({ theme }) => theme.colors.surface};
    border-top: 1px solid ${({ theme }) => theme.colors.border};
    padding-bottom: env(safe-area-inset-bottom);
  }
`;

const Tab = styled.a<{ $active?: boolean }>`
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: ${({ theme }) => theme.radii.md};
  color: ${({ theme }) => theme.colors.textMuted};
  font-weight: 650;
  transition: background-color ${({ theme }) => theme.motion.base}, color ${({ theme }) => theme.motion.base};
  &:hover { text-decoration: none; color: ${({ theme }) => theme.colors.textMain}; background: ${({ theme }) => theme.colors.surfaceSunken}; }
  svg {
    width: 20px;
    height: 20px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
    transition: background-color ${({ theme }) => theme.motion.base};
  }
  ${({ $active, theme }) =>
    $active &&
    css`
      color: ${theme.colors.primaryStrong};
      background: ${theme.colors.primarySoft};
      &:hover { color: ${theme.colors.primaryStrong}; background: ${theme.colors.primarySoft}; }
      svg { animation: ${hop} .35s ease; }
    `}
  ${({ theme }) => theme.media.phone} {
    flex: 1;
    flex-direction: column;
    justify-content: center;
    gap: 3px;
    min-height: ${({ theme }) => theme.layout.tabbar};
    padding: 8px 0;
    border-radius: 0;
    font-size: .68rem;
    &:hover { background: transparent; }
    ${({ $active, theme }) =>
      $active &&
      css`
        background: transparent;
        &:hover { background: transparent; }
        svg { width: 54px; height: 30px; padding: 4px 16px; border-radius: ${theme.radii.pill}; background: ${theme.colors.primarySoft}; }
      `}
  }
`;

// On a phone the tab shows the short label ("Claude" for "Ask Claude").
const TabLabel = styled.span<{ $short: string }>`
  ${({ theme }) => theme.media.phone} {
    font-size: 0;
    &::after { content: "${({ $short }) => $short}"; font-size: .68rem; }
  }
`;

const HelpButton = styled.button`
  flex: none;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid ${({ theme }) => theme.colors.border};
  background: ${({ theme }) => theme.colors.surface};
  color: ${({ theme }) => theme.colors.textMuted};
  font-weight: 800;
  font-size: 1rem;
  transition: color ${({ theme }) => theme.motion.base}, border-color ${({ theme }) => theme.motion.base},
    transform ${({ theme }) => theme.motion.fast};
  &:hover { color: ${({ theme }) => theme.colors.primaryStrong}; border-color: ${({ theme }) => theme.colors.primary}; }
  &:active { transform: scale(.94); }
`;

const Content = styled.main`
  max-width: ${({ theme }) => theme.layout.content};
  margin: 0 auto;
  padding: 24px 16px 48px;
  ${({ theme }) => theme.media.tablet} { padding: 32px 32px 64px; }
  ${({ theme }) => theme.media.phone} {
    padding-bottom: calc(${({ theme }) => theme.layout.tabbar} + 32px + env(safe-area-inset-bottom));
  }
`;

const Spacer = styled.span`
  display: none;
  ${({ theme }) => theme.media.phone} { display: block; margin-left: auto; }
`;

export default function App() {
  const route = useRoute();
  const active = sectionOf(route.name).id;
  useEffect(() => {
    document.title = documentTitle(route);
  }, [route]);
  if (route.name === "file") {
    return (
      <Suspense fallback={<Loading>Loading viewer…</Loading>}>
        <Page route={route} />
      </Suspense>
    );
  }
  return (
    <div>
      <TopBar>
        <Brand href={href.dashboard}>
          <img src="/favicon.svg" alt="" width={30} height={30} />
          <span>Study Companion</span>
        </Brand>
        <Tabs aria-label="Main">
          {SECTIONS.map((t) => (
            <Tab key={t.id} href={t.pages[0].href} $active={active === t.id} aria-current={active === t.id ? "page" : undefined}
              data-tour={`tab-${t.id}`} title={t.pages.map((p) => p.label).join(" · ")}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d={t.icon} /></svg>
              <TabLabel $short={t.short}>{t.label}</TabLabel>
            </Tab>
          ))}
          <Tab href="/settings">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="3" />
              <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" />
            </svg>
            <span>Settings</span>
          </Tab>
        </Tabs>
        <Spacer />
        <HelpButton type="button" onClick={startTour} aria-label="Show the tour" title="Show the tour" data-tour="help">
          ?
        </HelpButton>
        <ThemeSwitch />
      </TopBar>
      <Content>
        <SectionNav route={route} />
        <Suspense fallback={<Loading>Loading…</Loading>}>
          <Page route={route} />
        </Suspense>
      </Content>
      <Tour />
    </div>
  );
}
