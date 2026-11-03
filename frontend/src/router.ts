import { useEffect, useState } from "react";

// Hash routes (#/course/12) keep the server simple: it only ever serves index.html at /.
export type Route =
  | { name: "dashboard" }
  | { name: "courses" }
  | { name: "course"; id: number; section?: number }
  | { name: "study"; course?: number; section?: number; all?: boolean; due?: boolean }
  | { name: "plan" }
  | { name: "calendar" }
  | { name: "prompt"; course?: number }
  | { name: "file"; id: number; course?: number };

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
  if (parts[0] === "calendar") return { name: "calendar" };
  if (parts[0] === "prompt") {
    const course = params.get("course");
    return { name: "prompt", course: course && /^\d+$/.test(course) ? Number(course) : undefined };
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
  prompt: (course?: number) => `#/prompt${course ? `?course=${course}` : ""}`,
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
  file: (id: number, course?: number) => `#/file/${id}${course ? `?course=${course}` : ""}`,
};
