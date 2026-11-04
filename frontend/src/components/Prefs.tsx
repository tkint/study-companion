import { useRef, useState } from "react";
import type { ItemPrefs, ItemState } from "../api";

// The "⋯" menu on a deadline or a section: mark it optional or mandatory, or ignore it
// (backend: app/catchup.py). Ignored and optional work leaves the catch-up plan and target.

export function PrefsMenu({
  state,
  save,
  onChange,
  label,
}: {
  state: Pick<ItemState, "mandatory" | "ignored">;
  save: (prefs: ItemPrefs) => Promise<ItemState>;
  onChange: (s: ItemState) => void;
  label: string;
}) {
  const [busy, setBusy] = useState(false);
  const menu = useRef<HTMLDetailsElement>(null);

  async function apply(prefs: ItemPrefs) {
    setBusy(true);
    try {
      onChange(await save(prefs));
      if (menu.current) menu.current.open = false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="prefs-menu" ref={menu}>
      <summary className="btn small ghost" aria-label={`More for ${label}`} title="More">⋯</summary>
      <div className="prefs-pop" role="menu">
        <button role="menuitem" className="link" disabled={busy}
          onClick={() => apply({ criticality: state.mandatory ? "optional" : "mandatory" })}>
          {state.mandatory ? "Mark as optional" : "Mark as mandatory"}
        </button>
        <button role="menuitem" className="link" disabled={busy} onClick={() => apply({ ignored: !state.ignored })}>
          {state.ignored ? "Stop ignoring" : "Ignore (let it go)"}
        </button>
      </div>
    </details>
  );
}

export function PrefTags({ state }: { state: Pick<ItemState, "mandatory" | "ignored" | "criticality_by"> & { optional_reason?: string } }) {
  return (
    <>
      {state.ignored && <span className="tag muted-tag">ignored</span>}
      {!state.mandatory && !state.ignored && (
        <span className="tag muted-tag" title={state.optional_reason ? `Optional: ${state.optional_reason}` : "You marked it optional"}>
          optional
        </span>
      )}
    </>
  );
}
