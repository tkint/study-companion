import { useState } from "react";
import styled from "styled-components";

// The course's header image from Moodle, or a placeholder drawn from the course itself
// (a colour picked from its id and its initials) when it has none or it fails to load.

function hue(id: number): number {
  return (id * 137.508) % 360; // golden angle: neighbouring ids get distinct colours
}

export function initials(shortname: string, fullname: string): string {
  const words = (fullname || shortname).split(/[\s\-_/.:]+/u).filter((w) => /\p{L}|\p{N}/u.test(w));
  // Skip short words ("and", "de", "of") when there are enough long ones.
  const long = words.filter((w) => w.length > 3);
  const letters = (long.length >= 2 ? long : words).slice(0, 2).map((w) => [...w.replace(/^[^\p{L}\p{N}]+/u, "")][0] ?? "");
  return letters.join("").toUpperCase() || "?";
}

const Cover = styled.div`
  position: relative;
  overflow: hidden;
  display: grid;
  place-items: center;
  flex: none;
  background: linear-gradient(135deg, hsl(var(--cover-h) 70% 62%), hsl(var(--cover-h2) 65% 48%));
  color: #fff;
  font-weight: 700;
  letter-spacing: .02em;
  img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    background: ${({ theme }) => theme.colors.surface};
  }
  &.cover-thumb {
    width: 56px;
    height: 56px;
    border-radius: ${({ theme }) => theme.radii.md};
    font-size: 1.05rem;
    align-self: start;
  }
  &.cover-banner {
    width: 100%;
    aspect-ratio: 16 / 5;
    max-height: 220px;
    border-radius: ${({ theme }) => theme.radii.lg};
    margin: 4px 0 16px;
    font-size: clamp(2rem, 8vw, 3.5rem);
    box-shadow: ${({ theme }) => theme.shadows.card};
  }
  &.cover-fallback span { opacity: .9; text-shadow: 0 1px 2px rgb(0 0 0 / .15); }
  &.cover-banner.cover-fallback {
    background:
      radial-gradient(circle at 85% 20%, rgb(255 255 255 / .22) 0 18%, transparent 19%),
      radial-gradient(circle at 10% 110%, rgb(255 255 255 / .16) 0 30%, transparent 31%),
      linear-gradient(135deg, hsl(var(--cover-h) 70% 62%), hsl(var(--cover-h2) 65% 48%));
  }
  ${({ theme }) => theme.media.phone} {
    &.cover-thumb { width: 48px; height: 48px; font-size: .95rem; }
    &.cover-banner { aspect-ratio: 16 / 6; }
  }
`;

export function CourseCover({ id, shortname, fullname, imageUrl, variant }: {
  id: number;
  shortname: string;
  fullname: string;
  imageUrl: string | null | undefined;
  variant: "thumb" | "banner";
}) {
  const [failed, setFailed] = useState(false);
  const h = hue(id);
  const style = { "--cover-h": `${h}`, "--cover-h2": `${(h + 40) % 360}` } as React.CSSProperties;
  if (imageUrl && !failed) {
    return (
      <Cover className={`cover cover-${variant}`} style={style}>
        <img src={imageUrl} alt="" loading={variant === "thumb" ? "lazy" : "eager"} decoding="async"
          onError={() => setFailed(true)} />
      </Cover>
    );
  }
  return (
    <Cover className={`cover cover-${variant} cover-fallback`} style={style} aria-hidden="true">
      <span>{initials(shortname, fullname)}</span>
    </Cover>
  );
}
