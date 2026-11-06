import { useCallback, useEffect, useState } from "react";
import { Alert, Loading, ProgressBar } from "../ui";

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
  if (error) return <Alert role="alert">Could not load: {error}</Alert>;
  if (loading) return <Loading>Loading…</Loading>;
  return null;
}

export function Progress({ value, label = "Progress" }: { value: number | null; label?: string }) {
  return <ProgressBar value={value} label={label} />;
}
