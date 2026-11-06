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
  // Realistic catch-up (backend: app/catchup.py)
  mandatory: boolean;
  criticality: "mandatory" | "optional";
  criticality_by: "auto" | "you";
  optional_reason: string;
  ignored: boolean;
}

// What you chose for a deadline or a section: null criticality = automatic.
export interface ItemPrefs {
  ignored?: boolean;
  criticality?: "mandatory" | "optional" | null;
}

export interface ItemState {
  id: number;
  mandatory: boolean;
  criticality: "mandatory" | "optional";
  criticality_by: "auto" | "you";
  optional_reason: string;
  ignored: boolean;
}

export interface CatchUp {
  target_percent: number;
  percent: number;
  reached: boolean;
  done_items: number;
  total_items: number;
  done_minutes: number;
  total_minutes: number;
  left_minutes_to_target: number;
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
  image_url: string | null;
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
  study: StudyOverview;
  stats: Stats;
  plan: {
    hours_per_day: number;
    total_minutes: number;
    sections_left: number;
    sections_done: number;
    late: number;
    target_percent: number;
    projected_percent: number;
    optional_left_out: number;
    ignored: number;
    today: PlanDay | null;
  };
  catch_up: CatchUp;
}

// Positive stats for the home page (backend: app/stats.py).
export interface Stats {
  streak: number;
  best_streak: number;
  studied_today: boolean;
  week: { date: string; active: boolean }[];
  this_week: {
    deadlines_done: number;
    sections_studied: number;
    cards_reviewed: number;
    quizzes: number;
    quiz_percent: number | null;
  };
  total: {
    sections_studied: number;
    cards_learned: number;
    summaries: number;
    quizzes: number;
    deadlines_done: number;
  };
}

// ---- study loop (backend: app/study.py, app/planner, app/api/study.py)

export interface StudyNote {
  id: number;
  course_id: number;
  section_id: number;
  kind: string;
  title: string;
  markdown: string;
  source: string;
  created_at: number;
  updated_at: number;
}

export interface Question {
  id: number;
  course_id: number;
  section_id: number | null;
  kind: "short" | "mcq" | "flashcard" | string;
  question: string;
  answer: string;
  choices: string[];
  explanation: string;
  source: string;
  reps: number;
  lapses: number;
  interval: number;
  due_at: number | null;
  due: boolean;
  new: boolean;
  last_grade: number | null;
  created_at: number;
}

export interface QuizResult {
  id: number;
  course_id: number;
  section_id: number | null;
  source: "claude" | "web" | string;
  topic: string;
  score: number;
  total: number;
  percent: number | null;
  notes: string;
  taken_at: number;
  course_name?: string;
}

export interface CourseStudy {
  notes: StudyNote[];
  questions: Record<string, { questions: number; due: number }>;
  questions_total: number;
  questions_due: number;
  results: QuizResult[];
  studied: number[];
}

export interface StudyOverview {
  due: number;
  questions: number;
  courses: { id: number; fullname: string; shortname: string; enrolled: boolean; questions: number; due: number; new: number; notes: number }[];
  recent_results: QuizResult[];
}

export interface PlanItem {
  kind: "section" | "assign" | "quiz" | "event" | string;
  course_id: number | null;
  course_name: string;
  course_short: string;
  title: string;
  minutes: number;
  needed_by: number | null;
  needed_for: string;
  section_id: number | null;
  section_number: number | null;
  deadline_id: number | null;
  url: string;
  grade: number | null;
  pages: number;
  files: { id: number; name: string; pages: number }[];
  has_summary: boolean;
  questions: number;
  overdue: boolean;
  mandatory: boolean;
  catch_up: boolean; // behind (overdue, or needed by nothing upcoming) rather than upcoming
}

export interface PlanSlot extends PlanItem {
  minutes_today: number;
  part: number;
  parts: number;
  late: boolean;
}

export interface PlanDay {
  date: string;
  minutes: number;
  items: PlanSlot[];
}

export interface Plan {
  today: string;
  hours_per_day: number;
  total_minutes: number;
  sections_left: number;
  sections_done: number;
  late: number;
  notes: string[];
  days: PlanDay[];
  unscheduled: PlanItem[];
  unscheduled_minutes: number;
  target_percent: number;
  progress: CatchUp;
  projected_percent: number;
  beyond_target: PlanItem[];
  beyond_target_minutes: number;
  optional_left_out: number;
  ignored: number;
}

// ---- study time (backend: app/study_time.py)

export interface TimeEntry {
  id: number;
  course_id: number | null;
  course_name: string;
  course_shortname: string;
  started_at: number;
  minutes: number;
  source: "timer" | "manual" | "claude" | string;
  note: string;
}

export interface TimeSummary {
  today: string;
  today_minutes: number;
  week_minutes: number;
  last7_minutes: number;
  total_minutes: number;
  goal_minutes_per_day: number;
  streak_days: number;
  best_day: { date: string; minutes: number } | null;
  days: { date: string; minutes: number }[];
  courses: { course_id: number | null; course_name: string; course_shortname: string; minutes: number }[];
  recent: TimeEntry[];
}

// ---- reminders (backend: app/reminders.py)

export interface ReminderPrefs {
  deadline_alarms: number[];
  daily_enabled: boolean;
  daily_time: string;
}

export interface Reminders {
  now: number;
  cards_due: number;
  deadlines_soon: { id: number; name: string; due_at: number; course_shortname: string; url: string }[];
  planned_minutes: number;
  studied_minutes: number;
  goal_minutes: number;
  streak_days: number;
  prefs: ReminderPrefs;
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
  mandatory: boolean;
  criticality: "mandatory" | "optional";
  criticality_by: "auto" | "you";
  ignored: boolean;
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
  image_url: string | null;
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

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
  courseStudy: (id: number) => request<CourseStudy>(`/api/courses/${id}/study`),
  cards: (opts: { course?: number; section?: number; all?: boolean }) => {
    const q = new URLSearchParams();
    if (opts.course) q.set("course", String(opts.course));
    if (opts.section) q.set("section", String(opts.section));
    if (opts.all) q.set("all", "1");
    return request<{ now: number; questions: Question[]; overview: StudyOverview }>(`/api/study?${q}`);
  },
  review: (id: number, grade: number) =>
    request<Question>(`/api/study/questions/${id}/review`, { method: "POST", body: JSON.stringify({ grade }) }),
  deleteQuestion: (id: number) => request<{ deleted: number }>(`/api/study/questions/${id}`, { method: "DELETE" }),
  deleteNote: (id: number) => request<{ deleted: number }>(`/api/study/notes/${id}`, { method: "DELETE" }),
  saveResult: (r: { course_id: number; section_id?: number | null; score: number; total: number; topic?: string }) =>
    request<QuizResult>("/api/study/results", { method: "POST", body: JSON.stringify(r) }),
  deleteResult: (id: number) => request<{ deleted: number }>(`/api/study/results/${id}`, { method: "DELETE" }),
  setStudied: (sectionId: number, studied: boolean) =>
    request<{ id: number; studied: boolean }>(`/api/sections/${sectionId}/studied`, {
      method: "POST",
      body: JSON.stringify({ studied }),
    }),
  plan: (days = 14, course?: number, opts: { optional?: boolean; beyond?: boolean } = {}) => {
    const q = new URLSearchParams({ days: String(days) });
    if (course) q.set("course", String(course));
    if (opts.optional) q.set("optional", "1");
    if (opts.beyond) q.set("beyond", "1");
    return request<Plan>(`/api/plan?${q}`);
  },
  reminders: () => request<Reminders>("/api/reminders"),
  setReminders: (p: Partial<ReminderPrefs>) =>
    request<ReminderPrefs>("/api/reminders/settings", { method: "POST", body: JSON.stringify(p) }),
  studyTime: () => request<TimeSummary>("/api/study/time"),
  logTime: (e: { minutes: number; course_id?: number | null; started_at?: number; note?: string; source: "timer" | "manual" }) =>
    request<{ entry: { id: number; minutes: number }; summary: TimeSummary }>("/api/study/time", {
      method: "POST",
      body: JSON.stringify(e),
    }),
  deleteTime: (id: number) => request<{ deleted: number }>(`/api/study/time/${id}`, { method: "DELETE" }),
  setHours: (hours_per_day: number) =>
    request<{ hours_per_day: number }>("/api/plan/settings", { method: "POST", body: JSON.stringify({ hours_per_day }) }),
  setTarget: (target_percent: number) =>
    request<{ target_percent: number }>("/api/plan/settings", { method: "POST", body: JSON.stringify({ target_percent }) }),
  setDeadlinePrefs: (id: number, prefs: ItemPrefs) =>
    request<ItemState>(`/api/deadlines/${id}/prefs`, {
      method: "POST",
      body: JSON.stringify(prefs),
    }),
  setSectionPrefs: (id: number, prefs: ItemPrefs) =>
    request<ItemState>(`/api/sections/${id}/prefs`, {
      method: "POST",
      body: JSON.stringify(prefs),
    }),
};

export function fileUrl(f: Pick<FileInfo, "id" | "filename">, download = false): string {
  return `/files/${f.id}/${encodeURIComponent(f.filename)}${download ? "?download=1" : ""}`;
}
