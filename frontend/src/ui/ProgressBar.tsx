import styled from "styled-components";
import { tone, type Tone } from "../styles/theme";

const heights = { sm: "6px", md: "8px", lg: "12px" } as const;

const Track = styled.div<{ $size: keyof typeof heights }>`
  position: relative;
  height: ${({ $size }) => heights[$size]};
  border-radius: ${({ theme }) => theme.radii.pill};
  background: ${({ theme }) => theme.colors.surfaceSunken};
  box-shadow: inset 0 0 0 1px ${({ theme }) => theme.colors.border};
  overflow: visible;
`;

const Fill = styled.span<{ $color: string }>`
  display: block;
  height: 100%;
  border-radius: inherit;
  background: ${({ $color }) => $color};
  transition: width .8s ${({ theme }) => theme.motion.ease};
`;

const Marker = styled.span`
  position: absolute;
  top: -4px;
  bottom: -4px;
  width: 3px;
  margin-left: -1.5px;
  border-radius: 2px;
  background: ${({ theme }) => theme.colors.textMain};
  opacity: .55;
`;

export function ProgressBar({ value, size = "sm", tone: t = "primary", marker, label, className }: {
  value: number | null | undefined;
  size?: keyof typeof heights;
  tone?: Tone;
  /** A mark on the track, e.g. your goal, in percent. */
  marker?: number;
  /** Accessible name; without it the bar is decorative. */
  label?: string;
  className?: string;
}) {
  if (value == null) return null;
  const v = Math.max(0, Math.min(100, value));
  const a11y = label
    ? { role: "progressbar", "aria-label": label, "aria-valuenow": Math.round(v), "aria-valuemin": 0, "aria-valuemax": 100 }
    : { "aria-hidden": true };
  return (
    <Track $size={size} className={className} {...a11y}>
      <Fill $color={tone(t).solid} style={{ width: `${v}%` }} />
      {marker != null && <Marker style={{ left: `${Math.max(0, Math.min(100, marker))}%` }} aria-hidden="true" />}
    </Track>
  );
}
