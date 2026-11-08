import { useEffect, useState } from "react";

// Hash routes (#/course/12) keep the server simple: it only ever serves index.html at /.
export type Route =
  | { name: "dashboard" }
  | { name: "courses" }
  | { name: "course"; id: number; section?: number }
  | { name: "study"; course?: number; section?: number; all?: boolean; due?: boolean }
  | { name: "plan" }
  | { name: "time" }
  | { name: "calendar" }
  | { name: "prompt"; course?: number; prefill?: PromptPrefill }
  | { name: "templates"; id?: string }
  | { name: "file"; id: number; course?: number };

/** What a link into the prompt builder fills in (the calendar's "Build the session prompt"). */
export interface PromptPrefill {
  goal?: string;
  topic?: string;
  /** Section numbers (as in the builder's section picker), first and last. */
  sectionFrom?: number;
  sectionTo?: number;
  /** Time for the session, in minutes. */
  minutes?: number;
}

export function parse(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  const params = new URLSearchParams(query);
  if (parts[0] === "courses") return { name: "courses" };
  const num = (name: string) => {
    const v = params.get(name);
    return v && /^\d+$/.test(v) ? Number(v) : undefined;
  };
  if (parts[0] === "course" && /^\d+$/.test(parts[1] ?? "")) {
    return { name: "course", id: Number(parts[1]), section: num("section") };
  }
  if (parts[0] === "study") {
    return { name: "study", course: num("course"), section: num("section"), all: params.get("all") === "1",
      due: params.get("due") === "1" };
  }
  if (parts[0] === "plan") return { name: "plan" };
  // The timed schedule now lives in the calendar (old links and bookmarks still work).
  if (parts[0] === "schedule") return { name: "calendar" };
  if (parts[0] === "time") return { name: "time" };
  if (parts[0] === "calendar") return { name: "calendar" };
  if (parts[0] === "prompt") {
    const goal = params.get("goal");
    const topic = params.get("topic");
    const prefill: PromptPrefill = {
      goal: goal && /^\w{1,64}$/.test(goal) ? goal : undefined,
      topic: topic ? topic.slice(0, 200) : undefined,
      sectionFrom: num("section_from"),
      sectionTo: num("section_to"),
      minutes: num("minutes"),
    };
    const any = Object.values(prefill).some((v) => v !== undefined);
    return { name: "prompt", course: num("course"), ...(any ? { prefill } : {}) };
  }
  if (parts[0] === "templates") {
    const id = parts[1] && /^\w{1,64}$/.test(parts[1]) ? parts[1] : undefined;
    return { name: "templates", id };
  }
  if (parts[0] === "file" && /^\d+$/.test(parts[1] ?? "")) {
    const course = params.get("course");
    return { name: "file", id: Number(parts[1]), course: course ? Number(course) : undefined };
  }
  return { name: "dashboard" };
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parse(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export const href = {
  dashboard: "#/",
  courses: "#/courses",
  calendar: "#/calendar",
  prompt: (course?: number, prefill: PromptPrefill = {}) => {
    const q = new URLSearchParams();
    if (course) q.set("course", String(course));
    if (prefill.goal) q.set("goal", prefill.goal);
    if (prefill.topic) q.set("topic", prefill.topic);
    if (prefill.sectionFrom != null) q.set("section_from", String(prefill.sectionFrom));
    if (prefill.sectionTo != null) q.set("section_to", String(prefill.sectionTo));
    if (prefill.minutes) q.set("minutes", String(Math.round(prefill.minutes)));
    const qs = q.toString();
    return `#/prompt${qs ? `?${qs}` : ""}`;
  },
  templates: (id?: string) => `#/templates${id ? `/${id}` : ""}`,
  course: (id: number, section?: number) => `#/course/${id}${section ? `?section=${section}` : ""}`,
  study: (opts: { course?: number; section?: number; all?: boolean; due?: boolean } = {}) => {
    const q = new URLSearchParams();
    if (opts.due) q.set("due", "1");
    if (opts.course) q.set("course", String(opts.course));
    if (opts.section) q.set("section", String(opts.section));
    if (opts.all) q.set("all", "1");
    const qs = q.toString();
    return `#/study${qs ? `?${qs}` : ""}`;
  },
  plan: "#/plan",
  time: "#/time",
  file: (id: number, course?: number) => `#/file/${id}${course ? `?course=${course}` : ""}`,
};
