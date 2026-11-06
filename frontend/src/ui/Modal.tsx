import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import styled from "styled-components";
import { fadeIn, slideUp } from "../styles/motion";

// A dialog: a bottom sheet on a phone, a centred card on a computer. Closes with Escape, a
// tap on the backdrop or the close button; focus moves into it and back when it closes.

const Backdrop = styled.div`
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  background: ${({ theme }) => theme.colors.overlay};
  animation: ${fadeIn} ${({ theme }) => theme.motion.base} ease both;
  ${({ theme }) => theme.media.notPhone} { align-items: center; padding: 24px; }
`;

const Sheet = styled.div`
  width: 100%;
  max-width: 560px;
  max-height: 90vh;
  overflow: auto;
  display: grid;
  gap: 12px;
  padding: 18px 16px;
  padding-bottom: max(18px, env(safe-area-inset-bottom));
  background: ${({ theme }) => theme.colors.background};
  border-radius: ${({ theme }) => theme.radii.xl} ${({ theme }) => theme.radii.xl} 0 0;
  box-shadow: ${({ theme }) => theme.shadows.pop};
  animation: ${slideUp} .28s ${({ theme }) => theme.motion.ease} both;
  &:focus { outline: none; }
  ${({ theme }) => theme.media.notPhone} { border-radius: ${({ theme }) => theme.radii.xl}; padding: 20px; }
`;

const Grip = styled.span`
  justify-self: center;
  width: 40px;
  height: 4px;
  border-radius: 4px;
  background: ${({ theme }) => theme.colors.borderStrong};
  ${({ theme }) => theme.media.notPhone} { display: none; }
`;

export function Modal({ open, onClose, label, children }: {
  open: boolean;
  onClose: () => void;
  label: string;
  children: ReactNode;
}) {
  const sheet = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    sheet.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      before?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <Backdrop onClick={onClose}>
      <Sheet ref={sheet} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}
        onClick={(e) => e.stopPropagation()}>
        <Grip aria-hidden="true" />
        {children}
      </Sheet>
    </Backdrop>,
    document.body,
  );
}
