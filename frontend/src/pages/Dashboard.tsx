import { useEffect, useState } from "react";
import { api, type Dashboard as Data, type Deadline, type SyncState } from "../api";
import { Progress, Status, useLoad } from "../components/common";
import { DeadlineList } from "../components/DeadlineList";
import { fromNow } from "../format";
import { href } from "../router";

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
        <a className={`stat${overdue.filter((d) => !d.done).length ? " bad" : ""}`} href="#overdue">
          <strong>{overdue.filter((d) => !d.done).length}</strong>
          <span>overdue</span>
        </a>
        <a className="stat" href="#week">
          <strong>{week.filter((d) => !d.done).length}</strong>
          <span>due in 7 days</span>
        </a>
        <a className="stat" href="#later">
          <strong>{data.later.filter((d) => !d.done).length}</strong>
          <span>later</span>
        </a>
      </section>

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

      <section>
        <h2>Catch-up progress</h2>
        <CourseCards data={data} />
      </section>
      <p className="footnote">
        Study Companion {data.version} · <a href="/status">sync details</a>
      </p>
    </>
  );
}

export function CourseCards({ data }: { data: Pick<Data, "courses"> }) {
  if (!data.courses.length) return <p className="empty">No courses yet. Run a sync after connecting Moodle.</p>;
  return (
    <ul className="cards">
      {data.courses.map((c) => (
        <li key={c.id}>
          <a className="card" href={href.course(c.id)}>
            <div className="card-title">{c.fullname}</div>
            <div className="card-meta">
              <span>{c.shortname}</span>
              {c.overdue > 0 && <span className="late">{c.overdue} overdue</span>}
              {c.upcoming > 0 && <span>{c.upcoming} upcoming</span>}
            </div>
            {c.progress != null ? (
              <>
                <Progress value={c.progress} />
                <div className="card-meta">
                  <span>{Math.round(c.progress)}% complete</span>
                  {c.activities_tracked > 0 && (
                    <span>
                      {c.activities_done}/{c.activities_tracked} activities
                    </span>
                  )}
                </div>
              </>
            ) : (
              <div className="card-meta muted">No completion tracking in Moodle</div>
            )}
          </a>
        </li>
      ))}
    </ul>
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
