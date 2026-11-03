// Typed wrappers around the backend JSON API. Every call sends the session cookie; a 401
// means the session expired, so we go back to the (server-rendered) login page.

export interface Deadline {
  id: number;
  source: "assign" | "quiz" | "event" | string;
  kind: string;
  name: string;
  due_at: number;
  open_at: number | null;
  cutoff_at: number | null;
  closed: boolean;
  url: string;
  grade: number | null;
  course_id: number | null;
  course_name: string;
  course_shortname: string;
  module_id: number | null;
  done: boolean;
  done_by: "moodle" | "you" | null;
}

export interface CourseSummary {
  id: number;
  shortname: string;
  fullname: string;
  lang: string;
  progress: number | null;
  activities_done: number;
  activities_tracked: number;
  synced_at: number | null;
  overdue: number;
  upcoming: number;
}

export interface SyncRun {
  id: number;
  started_at: number;
  finished_at: number | null;
  trigger: string;
  status: "running" | "ok" | "partial" | "error" | string;
  courses: number;
  files_downloaded: number;
  files_failed: number;
  deadlines: number;
  message: string;
}

export interface SyncState {
  configured: boolean;
  running: boolean;
  last_run: SyncRun | null;
}

export interface Dashboard {
  now: number;
  overdue: Deadline[];
  this_week: Deadline[];
  later: Deadline[];
  courses: CourseSummary[];
  sync: SyncState;
  version: string;
}

export interface FileInfo {
  id: number;
  filename: string;
  filepath: string;
  mimetype: string;
  filesize: number;
  timemodified: number;
  status: string;
  available: boolean;
}

export interface FileDetail extends FileInfo {
  course_id: number;
  module_id: number;
}

export interface ModuleInfo {
  id: number;
  modname: string;
  name: string;
  description: string;
  url: string;
  visible: boolean;
  completion_state: number | null;
  files: FileInfo[];
}

export interface SectionInfo {
  id: number;
  number: number;
  name: string;
  summary: string;
  visible: boolean;
  modules: ModuleInfo[];
}

export interface CourseDetail {
  id: number;
  shortname: string;
  fullname: string;
  summary: string;
  lang: string;
  enrolled: boolean;
  progress: number | null;
  synced_at: number | null;
  sections: SectionInfo[];
  deadlines: Deadline[];
}

export interface Feed {
  url: string;
  webcal: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
    ...init,
  });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new ApiError(401, "Signed out");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, (data as { error?: string; status?: string }).error ?? (data as { status?: string }).status ?? res.statusText);
  return data as T;
}

export const api = {
  dashboard: () => request<Dashboard>("/api/dashboard"),
  course: (id: number) => request<CourseDetail>(`/api/courses/${id}`),
  deadlines: (from: number, to: number) =>
    request<{ deadlines: Deadline[] }>(`/api/deadlines?from=${from}&to=${to}`).then((r) => r.deadlines),
  setDone: (id: number, done: boolean) =>
    request<{ id: number; done: boolean }>(`/api/deadlines/${id}/done`, {
      method: "POST",
      body: JSON.stringify({ done }),
    }),
  file: (id: number) => request<FileDetail>(`/api/files/${id}`),
  sync: () => request<SyncState>("/api/sync"),
  startSync: () => request<{ status: string }>("/api/sync", { method: "POST" }),
  feed: () => request<Feed>("/api/calendar/feed"),
  newFeed: () => request<Feed>("/api/calendar/feed", { method: "POST" }),
};

export function fileUrl(f: Pick<FileInfo, "id" | "filename">, download = false): string {
  return `/files/${f.id}/${encodeURIComponent(f.filename)}${download ? "?download=1" : ""}`;
}
