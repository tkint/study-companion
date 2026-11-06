import styled, { css } from "styled-components";

// Buttons and button-looking links. Use `as="a"` for a link that looks like a button:
//   <Button as="a" href={...} $variant="primary" $size="sm">Let's go</Button>

export type ButtonVariant = "primary" | "soft" | "ghost" | "outline" | "success" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

interface ButtonProps {
  $variant?: ButtonVariant;
  $size?: ButtonSize;
  $block?: boolean;
}

const variants: Record<ButtonVariant, ReturnType<typeof css>> = {
  primary: css`
    background: ${({ theme }) => theme.colors.primaryStrong};
    color: ${({ theme }) => theme.colors.onPrimary};
    box-shadow: ${({ theme }) => theme.shadows.press};
    &:hover:not(:disabled) { background: ${({ theme }) => theme.colors.primaryHover}; }
  `,
  soft: css`
    background: ${({ theme }) => theme.colors.primarySoft};
    color: ${({ theme }) => theme.colors.primaryStrong};
    &:hover:not(:disabled) { background: color-mix(in srgb, ${({ theme }) => theme.colors.primary} 18%, transparent); }
  `,
  ghost: css`
    background: transparent;
    color: ${({ theme }) => theme.colors.textMain};
    &:hover:not(:disabled) { background: ${({ theme }) => theme.colors.surfaceSunken}; }
  `,
  outline: css`
    background: ${({ theme }) => theme.colors.surface};
    color: ${({ theme }) => theme.colors.textMain};
    border-color: ${({ theme }) => theme.colors.border};
    &:hover:not(:disabled) { border-color: ${({ theme }) => theme.colors.primary}; color: ${({ theme }) => theme.colors.primaryStrong}; }
  `,
  success: css`
    background: ${({ theme }) => theme.colors.successSoft};
    color: ${({ theme }) => theme.colors.successText};
    border-color: color-mix(in srgb, ${({ theme }) => theme.colors.success} 35%, transparent);
    &:hover:not(:disabled) { background: color-mix(in srgb, ${({ theme }) => theme.colors.success} 22%, transparent); }
  `,
  danger: css`
    background: transparent;
    color: ${({ theme }) => theme.colors.dangerText};
    border-color: color-mix(in srgb, ${({ theme }) => theme.colors.danger} 40%, transparent);
    &:hover:not(:disabled) { background: ${({ theme }) => theme.colors.dangerSoft}; }
  `,
};

const sizes: Record<ButtonSize, ReturnType<typeof css>> = {
  sm: css`
    min-height: 36px;
    padding: 6px 12px;
    font-size: ${({ theme }) => theme.fontSizes.sm};
    border-radius: ${({ theme }) => theme.radii.sm};
  `,
  md: css`
    min-height: ${({ theme }) => theme.layout.tap};
    padding: 10px 18px;
    font-size: ${({ theme }) => theme.fontSizes.base};
    border-radius: ${({ theme }) => theme.radii.md};
  `,
  lg: css`
    min-height: 52px;
    padding: 12px 22px;
    font-size: ${({ theme }) => theme.fontSizes.lg};
    border-radius: ${({ theme }) => theme.radii.md};
  `,
};

export const Button = styled.button<ButtonProps>`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: ${({ $block }) => ($block ? "100%" : "auto")};
  border: 1px solid transparent;
  font-weight: 650;
  line-height: 1.2;
  white-space: nowrap;
  text-decoration: none;
  user-select: none;
  cursor: pointer;
  transition: transform ${({ theme }) => theme.motion.fast} ease, background-color ${({ theme }) => theme.motion.base},
    border-color ${({ theme }) => theme.motion.base}, color ${({ theme }) => theme.motion.base};
  ${({ $size = "md" }) => sizes[$size]}
  ${({ $variant = "outline" }) => variants[$variant]}

  &:hover { text-decoration: none; }
  &:active:not(:disabled) { transform: translateY(1px) scale(.97); }
  &:disabled { opacity: .5; cursor: default; }
  svg { width: 1.1em; height: 1.1em; }
`;

/** A button that reads like a link: "Show more", "Delete", "Sync now". */
export const TextButton = styled.button<{ $danger?: boolean }>`
  display: inline;
  background: none;
  border: 0;
  padding: 0;
  margin: 0;
  font: inherit;
  font-weight: 600;
  color: ${({ theme, $danger }) => ($danger ? theme.colors.dangerText : theme.colors.primaryStrong)};
  cursor: pointer;
  &:hover:not(:disabled) { text-decoration: underline; text-underline-offset: 2px; }
  &:disabled { opacity: .5; }
`;

/** A square, icon-only button (needs an aria-label). */
export const IconButton = styled(Button).attrs<ButtonProps>((p) => ({ $variant: p.$variant ?? "ghost", $size: p.$size ?? "sm" }))`
  min-width: 36px;
  padding-left: 0;
  padding-right: 0;
  font-size: 1.05rem;
`;
