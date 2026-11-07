import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import styled from "styled-components";
import { href } from "../router";
import { fadeIn, pop } from "../styles/motion";
import { Button } from "../ui";

// A short guided tour: it walks through the sections, opening each page and pointing at the
// tab (or menu) that leads there. Runs once on the first visit; the "?" in the top bar plays
// it again. No library: a spotlight box over the target and a card next to it.

const SEEN_KEY = "tour-seen";
export const TOUR_EVENT = "study-tour:start";

interface Step {
  /** Page to show while this step is open. */
  go?: string;
  /** CSS selector of the element to point at; none centres the card. */
  target?: string;
  title: string;
  body: string;
}

const STEPS: Step[] = [
  {
    go: href.dashboard,
    title: "Welcome to Study Companion",
    body: "A one-minute tour of where things are. You can leave it at any time and replay it from the ? button.",
  },
  {
    go: href.dashboard,
    target: '[data-tour="tab-dashboard"]',
    title: "Today: your home page",
    body: "What to study today, what's due soon, and your week at a glance. Tap the logo or this tab to come back here.",
  },
  {
    go: href.dashboard,
    target: '[data-tour="subnav"]',
    title: "Pages inside a section",
    body: "Sections with more than one page show them here. Under Today: the catch-up plan, ordered by deadline.",
  },
  {
    go: href.courses,
    target: '[data-tour="tab-courses"]',
    title: "Courses",
    body: "Every course with its sections, files and deadlines. Open a PDF right in the app, mark sections as studied.",
  },
  {
    go: href.study(),
    target: '[data-tour="tab-study"]',
    title: "Study",
    body: "Flashcards your AI assistant saved for you, with spaced repetition. Study time (timer and daily goal) sits in the menu above.",
  },
  {
    go: href.calendar,
    target: '[data-tour="tab-calendar"]',
    title: "Calendar",
    body: "Your study blocks, deadlines and commitments in one calendar. Subscribe on your phone, download the .ics or print weeks as a PDF.",
  },
  {
    go: href.prompt(),
    target: '[data-tour="tab-prompt"]',
    title: "Ask AI",
    body: "Pick a course, a period and a goal, then copy the prompt into your AI assistant (Claude, ChatGPT, Gemini…) with the Study Companion connector on.",
  },
  {
    target: '[data-tour="help"]',
    title: "Lost? Tap ?",
    body: "This button plays the tour again. Settings (your source site and password) are in the last tab.",
  },
];

function seen(): boolean {
  try {
    return localStorage.getItem(SEEN_KEY) === "1";
  } catch {
    return true; // no storage: don't pop up on every visit
  }
}

function markSeen() {
  try {
    localStorage.setItem(SEEN_KEY, "1");
  } catch {
    /* private mode */
  }
}

export function startTour() {
  window.dispatchEvent(new Event(TOUR_EVENT));
}

const Catcher = styled.div`
  position: fixed;
  inset: 0;
  z-index: 80;
`;

const Spot = styled.div`
  position: fixed;
  z-index: 81;
  pointer-events: none;
  border-radius: ${({ theme }) => theme.radii.md};
  box-shadow: 0 0 0 3px ${({ theme }) => theme.colors.primary}, 0 0 0 9999px ${({ theme }) => theme.colors.overlay};
  transition: top .3s ${({ theme }) => theme.motion.ease}, left .3s ${({ theme }) => theme.motion.ease},
    width .3s ${({ theme }) => theme.motion.ease}, height .3s ${({ theme }) => theme.motion.ease};
`;

const Shade = styled.div`
  position: fixed;
  inset: 0;
  z-index: 81;
  pointer-events: none;
  background: ${({ theme }) => theme.colors.overlay};
  animation: ${fadeIn} .2s ease both;
`;

const CardBox = styled.div`
  position: fixed;
  z-index: 82;
  width: min(340px, calc(100vw - 32px));
  padding: 18px 18px 14px;
  border-radius: ${({ theme }) => theme.radii.lg};
  background: ${({ theme }) => theme.colors.surface};
  color: ${({ theme }) => theme.colors.textMain};
  box-shadow: ${({ theme }) => theme.shadows.pop};
  animation: ${pop} .22s ${({ theme }) => theme.motion.ease} both;
  &:focus { outline: none; }
  h2 { margin: 0 0 6px; font-size: ${({ theme }) => theme.fontSizes.lg}; }
  p { margin: 0 0 14px; color: ${({ theme }) => theme.colors.textMuted}; font-size: ${({ theme }) => theme.fontSizes.md}; }
`;

const Foot = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
`;

const Dots = styled.span`
  display: flex;
  gap: 4px;
  margin-right: auto;
  span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: ${({ theme }) => theme.colors.borderStrong};
    transition: background-color .2s, width .2s;
  }
  span[aria-current="step"] { width: 16px; border-radius: 3px; background: ${({ theme }) => theme.colors.primary}; }
`;

interface Box { top: number; left: number; width: number; height: number }

export function Tour() {
  const [step, setStep] = useState<number | null>(null);
  const [box, setBox] = useState<Box | null>(null);
  const card = useRef<HTMLDivElement>(null);
  const [cardPos, setCardPos] = useState<{ top: number; left: number } | null>(null);

  const close = useCallback(() => {
    markSeen();
    setStep(null);
    setBox(null);
  }, []);

  // Start on the first visit (once the page has had a moment to draw), or on request.
  useEffect(() => {
    const start = () => setStep(0);
    window.addEventListener(TOUR_EVENT, start);
    const t = seen() ? undefined : window.setTimeout(start, 900);
    return () => {
      window.removeEventListener(TOUR_EVENT, start);
      window.clearTimeout(t);
    };
  }, []);

  const s = step == null ? null : STEPS[step];

  // Open the step's page, then find its target (pages load lazily: try for a moment).
  useEffect(() => {
    if (!s) return;
    if (s.go && window.location.hash !== s.go && !(s.go === "#/" && window.location.hash === "")) {
      window.location.hash = s.go;
    }
    setBox(null);
    if (!s.target) return;
    let raf = 0;
    const until = performance.now() + 2000;
    const find = () => {
      const el = document.querySelector<HTMLElement>(s.target!);
      const r = el?.getBoundingClientRect();
      if (el && r && r.width > 0) {
        if (r.top < 0 || r.bottom > window.innerHeight) el.scrollIntoView({ block: "center" });
        const rr = el.getBoundingClientRect();
        setBox({ top: rr.top - 6, left: rr.left - 6, width: rr.width + 12, height: rr.height + 12 });
      } else if (performance.now() < until) {
        raf = requestAnimationFrame(find);
      }
    };
    raf = requestAnimationFrame(find);
    const onResize = () => {
      const el = document.querySelector<HTMLElement>(s.target!);
      const r = el?.getBoundingClientRect();
      if (r) setBox({ top: r.top - 6, left: r.left - 6, width: r.width + 12, height: r.height + 12 });
    };
    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, [s]);

  // The card goes below the target, or above it when there is no room (the phone tab bar).
  useLayoutEffect(() => {
    if (!s) return;
    const c = card.current;
    const w = c?.offsetWidth ?? 320;
    const h = c?.offsetHeight ?? 180;
    if (!box) {
      setCardPos({ top: Math.max(16, (window.innerHeight - h) / 2), left: Math.max(16, (window.innerWidth - w) / 2) });
      return;
    }
    const below = box.top + box.height + 12;
    const top = below + h < window.innerHeight - 8 ? below : Math.max(8, box.top - h - 12);
    const left = Math.min(Math.max(16, box.left + box.width / 2 - w / 2), window.innerWidth - w - 16);
    setCardPos({ top, left });
  }, [box, s, step]);

  useEffect(() => {
    if (step == null) return;
    card.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "ArrowRight") setStep((n) => (n == null ? n : Math.min(STEPS.length - 1, n + 1)));
      if (e.key === "ArrowLeft") setStep((n) => (n == null ? n : Math.max(0, n - 1)));
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [step, close]);

  if (step == null || !s) return null;
  const last = step === STEPS.length - 1;
  return createPortal(
    <>
      <Catcher onClick={close} aria-hidden="true" />
      {box ? <Spot style={box} aria-hidden="true" /> : <Shade aria-hidden="true" />}
      <CardBox ref={card} role="dialog" aria-modal="true" aria-labelledby="tour-title" tabIndex={-1}
        style={cardPos ?? { visibility: "hidden" }} key={step}>
        <h2 id="tour-title">{s.title}</h2>
        <p>{s.body}</p>
        <Foot>
          <Dots aria-label={`Step ${step + 1} of ${STEPS.length}`}>
            {STEPS.map((_, i) => <span key={i} aria-current={i === step ? "step" : undefined} />)}
          </Dots>
          {step === 0 ? (
            <Button $variant="ghost" $size="sm" onClick={close}>Skip</Button>
          ) : (
            <Button $variant="ghost" $size="sm" onClick={() => setStep(step - 1)}>Back</Button>
          )}
          <Button $variant="primary" $size="sm" onClick={() => (last ? close() : setStep(step + 1))}>
            {last ? "Done" : step === 0 ? "Show me" : "Next"}
          </Button>
        </Foot>
      </CardBox>
    </>,
    document.body,
  );
}
