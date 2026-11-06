import { createGlobalStyle, css } from "styled-components";
import { palette, type ColorName } from "./theme";

// Base styles only: the colour variables per scheme, a small reset and document defaults.
// Everything else is a styled component next to the markup that uses it.

const vars = (scheme: keyof typeof palette) =>
  (Object.keys(palette[scheme]) as ColorName[]).map((k) => `--c-${k}: ${palette[scheme][k]};`).join("\n");

const dark = css`
  color-scheme: dark;
  ${vars("dark")}
`;

export const GlobalStyle = createGlobalStyle`
  :root {
    color-scheme: light dark;
    ${vars("light")}
    -webkit-text-size-adjust: 100%;
  }
  /* Dark when the device is dark and no theme is forced, or when dark is chosen. */
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) { ${dark} }
  }
  :root[data-theme="dark"] { ${dark} }
  :root[data-theme="light"] { color-scheme: light; }

  *, *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; }
  body {
    background: ${({ theme }) => theme.colors.background};
    color: ${({ theme }) => theme.colors.textMain};
    font-family: ${({ theme }) => theme.fonts.body};
    font-size: 16px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    -webkit-tap-highlight-color: transparent;
  }
  img, svg, canvas { display: block; max-width: 100%; }
  button, input, select, textarea { font: inherit; color: inherit; }
  button { cursor: pointer; }
  button:disabled { cursor: default; }
  a { color: ${({ theme }) => theme.colors.primaryStrong}; text-decoration: none; }
  a:hover { text-decoration: underline; text-underline-offset: 2px; }
  :focus-visible {
    outline: 2px solid ${({ theme }) => theme.colors.primary};
    outline-offset: 2px;
    border-radius: 4px;
  }
  h1, h2, h3, h4 { line-height: 1.25; letter-spacing: -0.01em; }
  h1 { font-size: ${({ theme }) => theme.fontSizes.xl}; margin: 8px 0 4px; overflow-wrap: anywhere; }
  h2 { font-size: ${({ theme }) => theme.fontSizes.lg}; margin: 32px 0 12px; }
  h3 { font-size: ${({ theme }) => theme.fontSizes.md}; margin: 20px 0 8px; }
  p { margin: 0 0 12px; }
  code { font-family: ${({ theme }) => theme.fonts.mono}; font-size: .88em; }
  summary { cursor: pointer; }
  input[type="checkbox"], input[type="radio"] { accent-color: ${({ theme }) => theme.colors.primary}; }
  /* Anchor and scrollIntoView targets stop below the sticky top bar. */
  section, [id] { scroll-margin-top: calc(${({ theme }) => theme.layout.topbar} + 12px); }

  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation: none !important;
      transition: none !important;
      scroll-behavior: auto !important;
    }
  }
`;
