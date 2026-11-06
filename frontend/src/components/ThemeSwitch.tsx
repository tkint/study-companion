import type { ReactNode } from "react";
import styled from "styled-components";
import { useTheme, type Theme } from "../colorScheme";

const OPTIONS: { value: Theme; label: string; icon: ReactNode }[] = [
  {
    value: "light",
    label: "Light theme",
    icon: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </>
    ),
  },
  {
    value: "system",
    label: "Use the device theme",
    icon: (
      <>
        <rect x="3" y="4" width="18" height="12" rx="2" />
        <path d="M8 20h8M12 16v4" />
      </>
    ),
  },
  { value: "dark", label: "Dark theme", icon: <path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z" /> },
];

const Group = styled.div`
  display: inline-flex;
  flex: none;
  gap: 2px;
  padding: 3px;
  border-radius: ${({ theme }) => theme.radii.md};
  background: ${({ theme }) => theme.colors.surfaceSunken};
  button {
    display: flex;
    align-items: center;
    min-height: 32px;
    padding: 5px 8px;
    border: 0;
    border-radius: ${({ theme }) => theme.radii.sm};
    background: transparent;
    color: ${({ theme }) => theme.colors.textMuted};
    transition: background-color ${({ theme }) => theme.motion.base}, color ${({ theme }) => theme.motion.base};
    &:hover { color: ${({ theme }) => theme.colors.textMain}; }
    &[aria-pressed="true"] {
      background: ${({ theme }) => theme.colors.surface};
      color: ${({ theme }) => theme.colors.primaryStrong};
      box-shadow: ${({ theme }) => theme.shadows.card};
    }
  }
  svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
`;

export default function ThemeSwitch() {
  const [theme, setTheme] = useTheme();
  return (
    <Group role="group" aria-label="Theme">
      {OPTIONS.map((o) => (
        <button key={o.value} type="button" aria-pressed={theme === o.value} aria-label={o.label}
          title={o.label} onClick={() => setTheme(o.value)}>
          <svg viewBox="0 0 24 24" aria-hidden="true">{o.icon}</svg>
        </button>
      ))}
    </Group>
  );
}
