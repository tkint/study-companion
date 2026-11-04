import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ItemPrefs, ItemState } from "../api";

// The "⋯" menu on a deadline or a section: mark it optional or mandatory, or ignore it
// (backend: app/catchup.py). Ignored and optional work leaves the catch-up plan and target.
//
// The menu is rendered in a portal on <body> with fixed positioning: cards and sections
// create their own stacking contexts (animations, transforms), so a menu inside them would
// open behind the next card. It opens below the button, or above it near the bottom of the
// screen (the tab bar sits there on phones), and closes on outside tap, Escape or scroll.

const GAP = 4;
const MARGIN = 8;
const BOTTOM_BAR = 72; // the phone tab bar; harmless on wide screens

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
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);

  // Place the menu once it is rendered (its size is known then).
  useLayoutEffect(() => {
    if (!open || !button.current || !pop.current) return;
    const b = button.current.getBoundingClientRect();
    const m = pop.current.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const below = b.bottom + GAP;
    const fitsBelow = below + m.height <= vh - BOTTOM_BAR - MARGIN;
    const top = fitsBelow ? below : Math.max(MARGIN, b.top - GAP - m.height);
    const left = Math.min(Math.max(MARGIN, b.right - m.width), vw - m.width - MARGIN);
    setPos({ top, left });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!pop.current?.contains(t) && !button.current?.contains(t)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close();
        button.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    pop.current?.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

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
    <>
      <button ref={button} type="button" className="btn btn-sm btn-ghost prefs-btn" aria-label={`More for ${label}`}
        title="More" aria-haspopup="menu" aria-expanded={open}
        onClick={() => {
          setPos(null);
          setOpen(!open);
        }}>
        ⋯
      </button>
      {open && createPortal(
        <div ref={pop} className="prefs-pop" role="menu" aria-label={label}
          style={pos ? { top: pos.top, left: pos.left } : { top: 0, left: 0, visibility: "hidden" }}>
          <button role="menuitem" className="link" disabled={busy}
            onClick={() => apply({ criticality: state.mandatory ? "optional" : "mandatory" })}>
            {state.mandatory ? "Mark as optional" : "Mark as mandatory"}
          </button>
          <button role="menuitem" className="link" disabled={busy} onClick={() => apply({ ignored: !state.ignored })}>
            {state.ignored ? "Stop ignoring" : "Ignore (let it go)"}
          </button>
        </div>,
        document.body,
      )}
    </>
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
