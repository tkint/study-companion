import styled, { css } from "styled-components";
import { tone, type Tone } from "../styles/theme";
import { pop } from "../styles/motion";

/** A small label: "done", "optional", "3 cards". */
export const Badge = styled.span<{ $tone?: Tone; $dashed?: boolean; $pop?: boolean }>`
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 9px;
  border-radius: ${({ theme }) => theme.radii.pill};
  font-size: ${({ theme }) => theme.fontSizes.xs};
  font-weight: 650;
  line-height: 1.6;
  white-space: nowrap;
  vertical-align: middle;
  ${({ $tone = "neutral", $dashed, theme }) => {
    const t = tone($tone);
    return $dashed
      ? css`color: ${theme.colors.textMuted}; background: transparent; border: 1px dashed ${theme.colors.borderStrong};`
      : css`color: ${t.fg}; background: ${t.bg}; border: 1px solid transparent;`;
  }}
  ${({ $pop }) => $pop && css`animation: ${pop} .35s ${({ theme }) => theme.motion.spring} both;`}
`;
