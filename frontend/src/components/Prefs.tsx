import { useState } from "react";
import type { ItemPrefs, ItemState } from "../api";
import { Badge, Dropdown, MenuItem } from "../ui";

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
  const [open, setOpen] = useState(false);

  async function apply(prefs: ItemPrefs) {
    setBusy(true);
    try {
      onChange(await save(prefs));
      setOpen(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dropdown label={`More for ${label}`} open={open} onOpenChange={setOpen}>
      <MenuItem disabled={busy} onClick={() => apply({ criticality: state.mandatory ? "optional" : "mandatory" })}>
        {state.mandatory ? "Mark as optional" : "Mark as mandatory"}
      </MenuItem>
      <MenuItem disabled={busy} onClick={() => apply({ ignored: !state.ignored })}>
        {state.ignored ? "Stop ignoring" : "Ignore (let it go)"}
      </MenuItem>
    </Dropdown>
  );
}

export function PrefTags({ state }: { state: Pick<ItemState, "mandatory" | "ignored" | "criticality_by"> & { optional_reason?: string } }) {
  return (
    <>
      {state.ignored && <Badge $dashed>ignored</Badge>}
      {!state.mandatory && !state.ignored && (
        <Badge $dashed title={state.optional_reason ? `Optional: ${state.optional_reason}` : "You marked it optional"}>
          optional
        </Badge>
      )}
    </>
  );
}
