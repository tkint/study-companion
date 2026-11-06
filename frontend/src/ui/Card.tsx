import styled, { css } from "styled-components";
import { rise } from "../styles/motion";

type Pad = "none" | "sm" | "md" | "lg";
const pads: Record<Pad, string> = { none: "0", sm: "10px 14px", md: "14px 18px", lg: "20px 22px" };

export interface CardProps {
  $highlighted?: boolean;
  /** Lifts on hover: use for a card that is a link. */
  $interactive?: boolean;
  $pad?: Pad;
  $flat?: boolean;
  $muted?: boolean;
  $animate?: boolean;
}

export const Card = styled.div<CardProps>`
  display: block;
  min-width: 0;
  background: ${({ theme }) => theme.colors.surface};
  color: ${({ theme }) => theme.colors.textMain};
  border: 1px solid ${({ theme, $highlighted }) => ($highlighted ? theme.colors.primary : theme.colors.border)};
  border-radius: ${({ theme }) => theme.radii.lg};
  padding: ${({ $pad = "md" }) => pads[$pad]};
  box-shadow: ${({ theme, $flat }) => ($flat ? "none" : theme.shadows.card)};
  opacity: ${({ $muted }) => ($muted ? 0.6 : 1)};
  transition: transform ${({ theme }) => theme.motion.base} ease, border-color ${({ theme }) => theme.motion.base},
    box-shadow ${({ theme }) => theme.motion.base}, opacity ${({ theme }) => theme.motion.slow};
  ${({ $animate }) => $animate && css`animation: ${rise} .35s ease both;`}
  ${({ $interactive }) =>
    $interactive &&
    css`
      cursor: pointer;
      &:hover {
        text-decoration: none;
        transform: translateY(-2px);
        border-color: ${({ theme }) => theme.colors.primary};
        box-shadow: ${({ theme }) => theme.shadows.elevated};
      }
      &:active { transform: translateY(0); }
    `}
`;

/** The example from the design brief: a card that can be highlighted, lifting on hover. */
export const PlayfulCard = styled(Card).attrs({ $interactive: true, $pad: "lg" as const })`
  border-width: 2px;
`;

/** A card made of a <details>: tap the summary to open it. */
export const DetailsCard = styled.details<{ $muted?: boolean }>`
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.lg};
  box-shadow: ${({ theme }) => theme.shadows.card};
  padding: 0 18px;
  margin-bottom: ${({ theme }) => theme.layout.gap};
  animation: ${rise} .35s ease both;
  ${({ theme }) => theme.media.phone} { padding: 0 14px; }

  & > summary {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px 8px;
    padding: 14px 0;
    font-weight: 650;
    list-style: none;
    opacity: ${({ $muted }) => ($muted ? 0.6 : 1)};
    &::-webkit-details-marker { display: none; }
    &::before {
      content: "";
      flex: none;
      width: 8px;
      height: 8px;
      margin-right: 4px;
      border-right: 2px solid ${({ theme }) => theme.colors.textMuted};
      border-bottom: 2px solid ${({ theme }) => theme.colors.textMuted};
      transform: rotate(-45deg);
      transition: transform ${({ theme }) => theme.motion.base} ease;
    }
  }
  &[open] > summary {
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    margin-bottom: 8px;
    &::before { transform: rotate(45deg); }
  }
`;
