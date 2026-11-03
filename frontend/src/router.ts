import { useEffect, useState } from "react";

// Hash routes (#/course/12) keep the server simple: it only ever serves index.html at /.
export type Route =
  | { name: "dashboard" }
  | { name: "courses" }
  | { name: "course"; id: number }
  | { name: "calendar" }
  | { name: "file"; id: number; course?: number };

export function parse(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  const params = new URLSearchParams(query);
  if (parts[0] === "courses") return { name: "courses" };
  if (parts[0] === "course" && /^\d+$/.test(parts[1] ?? "")) return { name: "course", id: Number(parts[1]) };
  if (parts[0] === "calendar") return { name: "calendar" };
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
  course: (id: number) => `#/course/${id}`,
  file: (id: number, course?: number) => `#/file/${id}${course ? `?course=${course}` : ""}`,
};
