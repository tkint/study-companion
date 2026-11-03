import { useCallback, useEffect, useState } from "react";

export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(load, deps);
  const reload = useCallback(() => {
    run()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message || "Could not load"));
  }, [run]);
  useEffect(reload, [reload]);
  return { data, error, reload, setData };
}

export function Status({ error, loading }: { error: string | null; loading: boolean }) {
  if (error) return <p className="alert" role="alert">Could not load: {error}</p>;
  if (loading) return <p className="loading">Loading…</p>;
  return null;
}

export function Progress({ value }: { value: number | null }) {
  if (value == null) return null;
  const v = Math.max(0, Math.min(100, value));
  return (
    <div className="progress" role="progressbar" aria-valuenow={Math.round(v)} aria-valuemin={0} aria-valuemax={100}>
      <span style={{ width: `${v}%` }} />
    </div>
  );
}
