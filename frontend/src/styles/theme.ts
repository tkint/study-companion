// Design tokens for the whole UI. Components read them through styled-components'
// ThemeProvider (`${({ theme }) => theme.colors.primary}`).
//
// Colours resolve to CSS custom properties, so the light/dark switch (src/colorScheme.ts, and
// the inline script in index.html that runs before the first paint) only flips an attribute
// on <html>: no React re-render, no flash. The values live in `palette` below and
// GlobalStyle writes them out as variables for each scheme.
//
// Direction: calm slate neutrals, one friendly blue for anything you can act on, a warm
// amber for highlights, and clear status colours. Flat surfaces, soft shadows, no glow.

export const palette = {
  light: {
    primary: "#3B82F6", // friendly, energetic blue: focus rings, progress, selected states
    primaryHover: "#2563EB",
    primaryStrong: "#2563EB", // filled buttons and link text (passes AA on white)
    primarySoft: "#EFF6FF",
    onPrimary: "#FFFFFF",
    accent: "#F59E0B", // playful warm accent for highlights
    accentSoft: "#FEF3C7",
    accentText: "#B45309",
    success: "#10B981", // clean completion green
    successSoft: "#ECFDF5",
    successText: "#047857",
    danger: "#E11D48",
    dangerSoft: "#FFF1F2",
    dangerText: "#BE123C",
    warning: "#F59E0B",
    warningSoft: "#FFFBEB",
    warningText: "#B45309",
    sky: "#0EA5E9",
    coral: "#F97316",
    background: "#F8FAFC", // soft, readable backdrop
    surface: "#FFFFFF",
    surfaceSunken: "#F1F5F9",
    textMain: "#0F172A",
    textMuted: "#475569",
    border: "#E2E8F0",
    borderStrong: "#CBD5E1",
    overlay: "rgba(15, 23, 42, 0.45)",
    shadowTint: "15, 23, 42",
  },
  dark: {
    primary: "#60A5FA",
    primaryHover: "#93C5FD",
    primaryStrong: "#60A5FA",
    primarySoft: "#172554",
    onPrimary: "#0B1220",
    accent: "#FBBF24",
    accentSoft: "#3A2A0B",
    accentText: "#FCD34D",
    success: "#34D399",
    successSoft: "#0B2E24",
    successText: "#6EE7B7",
    danger: "#FB7185",
    dangerSoft: "#3B1220",
    dangerText: "#FDA4AF",
    warning: "#FBBF24",
    warningSoft: "#33270F",
    warningText: "#FCD34D",
    sky: "#38BDF8",
    coral: "#FB923C",
    background: "#0B1220",
    surface: "#131C2E",
    surfaceSunken: "#0F1727",
    textMain: "#E2E8F0",
    textMuted: "#94A3B8",
    border: "#24324A",
    borderStrong: "#334462",
    overlay: "rgba(2, 6, 23, 0.7)",
    shadowTint: "0, 0, 0",
  },
} as const;

export type ColorName = keyof typeof palette.light;

// The colour of the browser/system bars per scheme (index.html, colorScheme.ts and the
// server's manifest in backend/app/main.py use the same values).
export const barColors = { light: palette.light.surface, dark: palette.dark.surface } as const;

const cssVar = (name: ColorName) => `var(--c-${name})`;

const colors = Object.fromEntries(
  (Object.keys(palette.light) as ColorName[]).map((k) => [k, cssVar(k)]),
) as { [K in ColorName]: string };

export const theme = {
  colors,
  radii: {
    sm: "8px",
    md: "12px",
    lg: "16px",
    xl: "22px",
    pill: "9999px",
  },
  space: {
    xxs: "2px",
    xs: "4px",
    sm: "8px",
    md: "12px",
    lg: "16px",
    xl: "24px",
    xxl: "32px",
    xxxl: "48px",
  },
  shadows: {
    card: "0 1px 2px rgba(var(--c-shadowTint), 0.04), 0 2px 6px -1px rgba(var(--c-shadowTint), 0.04)",
    elevated: "0 10px 15px -3px rgba(var(--c-shadowTint), 0.08), 0 4px 6px -2px rgba(var(--c-shadowTint), 0.05)",
    pop: "0 12px 32px -6px rgba(var(--c-shadowTint), 0.22)",
    press: "inset 0 -2px 0 rgba(var(--c-shadowTint), 0.12)",
  },
  fonts: {
    body: 'ui-rounded, "SF Pro Rounded", "Nunito", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    mono: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  },
  fontSizes: {
    xs: "0.75rem",
    sm: "0.85rem",
    md: "0.95rem",
    base: "1rem",
    lg: "1.1rem",
    xl: "1.5rem",
    xxl: "1.8rem",
  },
  layout: {
    topbar: "60px",
    tabbar: "64px",
    content: "1200px",
    gap: "12px",
    tap: "44px", // smallest comfortable touch target
  },
  media: {
    phone: "@media (max-width: 640px)",
    notPhone: "@media (min-width: 641px)",
    small: "@media (max-width: 520px)",
    tablet: "@media (min-width: 900px)",
    desktop: "@media (min-width: 1024px)",
  },
  motion: {
    fast: "120ms",
    base: "200ms",
    slow: "400ms",
    ease: "cubic-bezier(.2, .8, .2, 1)",
    spring: "cubic-bezier(.3, 1.5, .5, 1)",
  },
} as const;

export type AppTheme = typeof theme;

export type Tone = "neutral" | "primary" | "accent" | "success" | "danger" | "warning" | "sky" | "coral";

/** Foreground, soft background and solid colour for a tone, for badges, icons and tiles. */
export function tone(t: Tone): { fg: string; bg: string; solid: string } {
  const c = theme.colors;
  switch (t) {
    case "primary":
      return { fg: c.primaryStrong, bg: c.primarySoft, solid: c.primary };
    case "accent":
      return { fg: c.accentText, bg: c.accentSoft, solid: c.accent };
    case "success":
      return { fg: c.successText, bg: c.successSoft, solid: c.success };
    case "danger":
      return { fg: c.dangerText, bg: c.dangerSoft, solid: c.danger };
    case "warning":
      return { fg: c.warningText, bg: c.warningSoft, solid: c.warning };
    case "sky":
      return { fg: c.sky, bg: `color-mix(in srgb, ${c.sky} 14%, transparent)`, solid: c.sky };
    case "coral":
      return { fg: c.coral, bg: `color-mix(in srgb, ${c.coral} 14%, transparent)`, solid: c.coral };
    default:
      return { fg: c.textMuted, bg: c.surfaceSunken, solid: c.borderStrong };
  }
}
