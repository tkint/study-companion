import styled, { css } from "styled-components";
import { tone, type Tone } from "../styles/theme";
import { rise, stagger } from "../styles/motion";

// Layout helpers and the small text pieces every page uses.

export const Row = styled.div<{ $gap?: string; $justify?: string; $align?: string; $nowrap?: boolean; $tight?: boolean }>`
  display: flex;
  flex-wrap: ${({ $nowrap }) => ($nowrap ? "nowrap" : "wrap")};
  align-items: ${({ $align = "center" }) => $align};
  justify-content: ${({ $justify = "flex-start" }) => $justify};
  gap: ${({ $gap = "8px" }) => $gap};
  margin: ${({ $tight }) => ($tight ? "0" : "12px 0")};
  min-width: 0;
`;

export const Stack = styled.div<{ $gap?: string }>`
  display: grid;
  gap: ${({ $gap = "12px" }) => $gap};
  min-width: 0;
`;

/** A list without bullets whose items slide in one after another. */
export const List = styled.ul<{ $gap?: string; $animate?: boolean }>`
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: ${({ $gap, theme }) => $gap ?? theme.layout.gap};
  ${({ $animate = true }) =>
    $animate &&
    css`
      & > li { animation: ${rise} .35s ease both; ${stagger()} }
    `}
`;

export const Muted = styled.span<{ $small?: boolean }>`
  color: ${({ theme }) => theme.colors.textMuted};
  ${({ $small, theme }) => $small && css`font-size: ${theme.fontSizes.sm};`}
`;

export const Lead = styled.p<{ $small?: boolean }>`
  margin: 4px 0 16px;
  max-width: 68ch;
  color: ${({ theme }) => theme.colors.textMuted};
  font-size: ${({ $small, theme }) => ($small ? theme.fontSizes.sm : theme.fontSizes.base)};
`;

export const Small = styled.p<{ $muted?: boolean }>`
  margin: 6px 0;
  font-size: ${({ theme }) => theme.fontSizes.sm};
  color: ${({ $muted, theme }) => ($muted ? theme.colors.textMuted : "inherit")};
`;

export const Late = styled.span`
  color: ${({ theme }) => theme.colors.dangerText};
  font-weight: 650;
`;

export const Crumbs = styled.p`
  margin: 0 0 4px;
  font-size: ${({ theme }) => theme.fontSizes.md};
  font-weight: 600;
`;

/** A heading with a link or action on its right. */
export const SectionHead = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  & > h2 { margin-bottom: 12px; }
  & > a { margin-top: 20px; font-size: ${({ theme }) => theme.fontSizes.sm}; font-weight: 600; white-space: nowrap; }
`;

/** A section title with an icon in a soft tile. */
export const Title = styled.h2`
  display: flex;
  align-items: center;
  gap: 10px;
  & > svg {
    width: 30px;
    height: 30px;
    padding: 6px;
    border-radius: ${({ theme }) => theme.radii.sm};
    color: ${({ theme }) => theme.colors.primaryStrong};
    background: ${({ theme }) => theme.colors.primarySoft};
  }
`;

export const Empty = styled.p`
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0;
  color: ${({ theme }) => theme.colors.textMuted};
  & > svg { color: ${({ theme }) => theme.colors.success}; }
`;

export const Loading = styled.p`
  color: ${({ theme }) => theme.colors.textMuted};
`;

/** A message in a tinted box: errors, warnings, hints. */
export const Alert = styled.div<{ $tone?: Tone }>`
  margin: 8px 0 12px;
  padding: 10px 14px;
  border-radius: ${({ theme }) => theme.radii.md};
  font-size: ${({ theme }) => theme.fontSizes.md};
  ${({ $tone = "danger", theme }) => {
    const t = tone($tone);
    return css`
      color: ${$tone === "danger" ? t.fg : theme.colors.textMain};
      background: ${t.bg};
      border: 1px solid color-mix(in srgb, ${t.solid} 35%, transparent);
    `;
  }}
  & > ul { margin: 0; padding-left: 18px; }
  a { font-weight: 600; }
`;

/** A strip with a message and an action on the right. */
export const Banner = styled.div<{ $tone?: Tone }>`
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
  padding: 10px 10px 10px 16px;
  border-radius: ${({ theme }) => theme.radii.lg};
  ${({ $tone = "primary" }) => {
    const t = tone($tone);
    return css`background: ${t.bg}; border: 1px solid color-mix(in srgb, ${t.solid} 20%, transparent);`;
  }}
  & > span { display: inline-flex; align-items: center; gap: 8px; }
  svg { color: ${({ theme }) => theme.colors.primaryStrong}; width: 1.2em; height: 1.2em; }
`;

export const StatGrid = styled.section<{ $cols?: number }>`
  display: grid;
  grid-template-columns: repeat(${({ $cols = 3 }) => $cols}, minmax(0, 1fr));
  gap: ${({ theme }) => theme.layout.gap};
  margin: 12px 0;
`;

export const Stat = styled.div<{ $tone?: Tone }>`
  display: grid;
  justify-items: center;
  align-content: center;
  gap: 2px;
  padding: 14px 6px;
  text-align: center;
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme, $tone }) => ($tone ? `color-mix(in srgb, ${tone($tone).solid} 45%, transparent)` : theme.colors.border)};
  border-radius: ${({ theme }) => theme.radii.lg};
  box-shadow: ${({ theme }) => theme.shadows.card};
  & > strong {
    font-size: 1.4rem;
    line-height: 1.15;
    font-variant-numeric: tabular-nums;
    color: ${({ $tone }) => ($tone ? tone($tone).fg : "inherit")};
  }
  & > span { font-size: ${({ theme }) => theme.fontSizes.sm}; color: ${({ theme }) => theme.colors.textMuted}; }
  ${({ theme }) => theme.media.small} { & > strong { font-size: 1.15rem; } }
`;

/** The coloured stripe of a course on a row. */
export const Swatch = styled.span`
  flex: none;
  align-self: stretch;
  width: 5px;
  border-radius: 5px;
`;

export const VisuallyHidden = styled.span`
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
`;

export const Footnote = styled.p`
  margin-top: 36px;
  text-align: center;
  font-size: ${({ theme }) => theme.fontSizes.sm};
  color: ${({ theme }) => theme.colors.textMuted};
`;

/** Tags and facts under a title: course, source, "optional"… */
export const Meta = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 8px;
  margin: 4px 0;
  font-size: ${({ theme }) => theme.fontSizes.sm};
  color: ${({ theme }) => theme.colors.textMuted};
  & > a { font-weight: 650; }
`;

/** A <details> without a card, for "past" and "beyond your goal" lists. */
export const Fold = styled.details`
  margin-top: 16px;
  & > summary { padding: 8px 0; color: ${({ theme }) => theme.colors.textMuted}; font-weight: 600; }
`;

/** Preformatted text that wraps: prompts, built-in templates. */
export const Pre = styled.pre`
  margin: 8px 0 0;
  max-height: 50vh;
  overflow: auto;
  padding: 12px;
  border-radius: ${({ theme }) => theme.radii.sm};
  background: ${({ theme }) => theme.colors.surfaceSunken};
  font-family: ${({ theme }) => theme.fonts.mono};
  font-size: ${({ theme }) => theme.fontSizes.sm};
  white-space: pre-wrap;
  overflow-wrap: anywhere;
`;
