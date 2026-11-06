import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import styled from "styled-components";
import { pop } from "../styles/motion";
import { IconButton } from "./Button";

// A small menu under a "⋯" button. The menu is drawn in a portal with fixed positioning, so
// list items, cards and their animations can never paint over it (the old stacking bug).
// Closes on Escape, a tap outside, or picking an item.

const Pop = styled.div`
  position: fixed;
  z-index: 60;
  display: grid;
  gap: 2px;
  min-width: 200px;
  padding: 6px;
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.md};
  box-shadow: ${({ theme }) => theme.shadows.pop};
  transform-origin: top right;
  animation: ${pop} .16s ${({ theme }) => theme.motion.ease} both;
`;

export const MenuItem = styled.button.attrs({ type: "button", role: "menuitem" })`
  display: block;
  width: 100%;
  min-height: 40px;
  padding: 8px 12px;
  border: 0;
  border-radius: ${({ theme }) => theme.radii.sm};
  background: transparent;
  color: ${({ theme }) => theme.colors.textMain};
  font-weight: 550;
  text-align: left;
  &:hover:not(:disabled), &:focus-visible { background: ${({ theme }) => theme.colors.surfaceSunken}; outline: none; }
  &:disabled { opacity: .5; }
`;

export function Dropdown({ label, trigger = "⋯", children, open: controlled, onOpenChange }: {
  /** Accessible name of the trigger button. */
  label: string;
  trigger?: ReactNode;
  children: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [own, setOwn] = useState(false);
  const open = controlled ?? own;
  const setOpen = useCallback((v: boolean) => {
    setOwn(v);
    onOpenChange?.(v);
  }, [onOpenChange]);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);
  const id = useId();

  // Sits under the button (above it near the bottom of the screen) and follows it on scroll.
  const place = useCallback(() => {
    if (!button.current) return;
    const r = button.current.getBoundingClientRect();
    const height = menu.current?.offsetHeight ?? 100;
    const below = r.bottom + 4 + height < window.innerHeight;
    setPos({ top: below ? r.bottom + 4 : Math.max(8, r.top - 4 - height), right: Math.max(8, window.innerWidth - r.right) });
  }, []);

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus({ preventScroll: true });
    const close = () => setOpen(false);
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!menu.current?.contains(t) && !button.current?.contains(t)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close();
        button.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, setOpen, place]);

  return (
    <>
      <IconButton ref={button} type="button" aria-label={label} title={label} aria-haspopup="menu"
        aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => setOpen(!open)}>
        {trigger}
      </IconButton>
      {open && createPortal(
        <Pop ref={menu} id={id} role="menu" style={pos ? { top: pos.top, right: pos.right } : { visibility: "hidden" }}>
          {children}
        </Pop>,
        document.body,
      )}
    </>
  );
}
