import { useEffect, useState } from "react";
import { api, type Deadline, type SyncState } from "../api";
import { Status, useLoad } from "../components/common";
import { CourseList } from "../components/CourseList";
import { DeadlineList } from "../components/DeadlineList";
import { fromNow } from "../format";

function replace(list: Deadline[], d: Deadline) {
  return list.map((x) => (x.id === d.id ? d : x));
}

export default function Dashboard() {
  const { data, error, reload, setData } = useLoad(api.dashboard, []);

  function changed(d: Deadline) {
    if (!data) return;
    // Keep the item in place until the next load, so "Undo" stays under your thumb.
    setData({
      ...data,
      overdue: replace(data.overdue, d),
      this_week: replace(data.this_week, d),
      later: replace(data.later, d),
    });
  }

  if (!data) return <Status error={error} loading />;
  const overdue = data.overdue;
  const week = data.this_week;
  return (
    <>
      <SyncBar sync={data.sync} onDone={reload} />
      <section className="summary" aria-label="Summary">
        <Stat target="overdue" count={overdue.filter((d) => !d.done).length} label="overdue" bad />
        <Stat target="week" count={week.filter((d) => !d.done).length} label="due in 7 days" />
        <Stat target="later" count={data.later.filter((d) => !d.done).length} label="later" />
      </section>

      <div className="dash">
        <div>
          <section id="overdue">
            <h2>Overdue</h2>
            <DeadlineList items={overdue} empty="Nothing overdue. Nice." onChange={changed} />
          </section>
          <section id="week">
            <h2>Due in the next 7 days</h2>
            <DeadlineList items={week} empty="Nothing due this week." onChange={changed} />
          </section>
          <section id="later">
            <h2>Later</h2>
            <DeadlineList items={data.later} empty="Nothing scheduled yet." onChange={changed} />
          </section>
        </div>
        <section className="dash-side" id="progress">
          <h2>Catch-up progress</h2>
          <CourseList courses={data.courses} search={data.courses.length > 4} />
        </section>
      </div>
      <p className="footnote">
        Study Companion {data.version} · <a href="/status">sync details</a>
      </p>
    </>
  );
}

// Buttons rather than #anchors: the hash is the app's route, and scrollIntoView honours the
// scroll-margin that keeps the heading clear of the sticky top bar.
function Stat({ target, count, label, bad }: { target: string; count: number; label: string; bad?: boolean }) {
  return (
    <button type="button" className={`stat${bad && count ? " bad" : ""}`}
      onClick={() => document.getElementById(target)?.scrollIntoView({ behavior: "smooth", block: "start" })}>
      <strong>{count}</strong>
      <span>{label}</span>
    </button>
  );
}

function SyncBar({ sync: initial, onDone }: { sync: SyncState; onDone: () => void }) {
  const [sync, setSync] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setSync(initial), [initial]);

  useEffect(() => {
    if (!sync.running) return;
    const t = window.setInterval(async () => {
      try {
        const s = await api.sync();
        setSync(s);
        if (!s.running) onDone();
      } catch {
        /* keep polling */
      }
    }, 3000);
    return () => window.clearInterval(t);
  }, [sync.running, onDone]);

  async function start() {
    setError(null);
    try {
      await api.startSync();
      setSync({ ...sync, running: true });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!sync.configured) {
    return (
      <p className="banner warn">
        Moodle is not connected yet. <a href="/settings">Open Settings</a> to add your Moodle address and token.
      </p>
    );
  }
  const run = sync.last_run;
  return (
    <div className={`banner${run && run.status !== "ok" && !sync.running ? " warn" : ""}`}>
      <span>
        {sync.running
          ? "Syncing with Moodle…"
          : run
            ? `Last sync ${fromNow(run.finished_at ?? run.started_at)}${run.status === "ok" ? "" : ` (${run.status})`}`
            : "Not synced yet"}
        {error && <span className="late"> · {error}</span>}
      </span>
      <button className="btn small" onClick={start} disabled={sync.running}>
        {sync.running ? "Syncing…" : "Sync now"}
      </button>
    </div>
  );
}
