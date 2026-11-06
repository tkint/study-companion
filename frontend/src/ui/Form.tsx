import styled, { css } from "styled-components";

// Form controls. 16px text in inputs keeps iOS from zooming in on focus.

const control = css`
  width: 100%;
  min-height: ${({ theme }) => theme.layout.tap};
  padding: 9px 12px;
  font-size: 16px;
  color: ${({ theme }) => theme.colors.textMain};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.borderStrong};
  border-radius: ${({ theme }) => theme.radii.md};
  transition: border-color ${({ theme }) => theme.motion.base}, box-shadow ${({ theme }) => theme.motion.base};
  &:hover:not(:disabled) { border-color: ${({ theme }) => theme.colors.primary}; }
  &:focus {
    outline: none;
    border-color: ${({ theme }) => theme.colors.primary};
    box-shadow: 0 0 0 3px color-mix(in srgb, ${({ theme }) => theme.colors.primary} 25%, transparent);
  }
  &:disabled { opacity: .6; }
`;

export const Input = styled.input`${control}`;
export const Select = styled.select`${control}`;
export const Textarea = styled.textarea`
  ${control}
  display: block;
  line-height: 1.5;
  resize: vertical;
`;

/** A group of controls with a title, as a card. */
export const Fieldset = styled.fieldset`
  min-width: 0;
  margin: 0 0 12px;
  padding: 12px 16px 16px;
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.lg};
  box-shadow: ${({ theme }) => theme.shadows.card};
  & > legend {
    padding: 0 6px;
    margin-left: -6px;
    font-weight: 700;
  }
`;

/** A label above its control. */
export const Field = styled.label`
  display: grid;
  gap: 6px;
  margin-top: 10px;
  min-width: 0;
  font-size: ${({ theme }) => theme.fontSizes.sm};
  font-weight: 600;
  color: ${({ theme }) => theme.colors.textMuted};
`;

/** Fields side by side that wrap on a phone. */
export const FieldRow = styled.div<{ $min?: string }>`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(${({ $min = "140px" }) => $min}, 1fr));
  gap: 10px;
  & > ${Field} { margin-top: 10px; }
`;

/** A checkbox (or radio) with its text, a full-height row to tap. */
export const Check = styled.label`
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  cursor: pointer;
  & > input { width: 20px; height: 20px; margin: 0; flex: none; }
`;

/** A pill-shaped checkbox, for a few short choices. */
export const Chip = styled.label`
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 6px 14px;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.pill};
  background: ${({ theme }) => theme.colors.surface};
  font-weight: 550;
  cursor: pointer;
  transition: border-color ${({ theme }) => theme.motion.base}, background-color ${({ theme }) => theme.motion.base};
  & > input { width: 18px; height: 18px; margin: 0; }
  &:has(input:checked) {
    border-color: ${({ theme }) => theme.colors.primary};
    background: ${({ theme }) => theme.colors.primarySoft};
  }
`;

export const Chips = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 6px;
`;

/** One-of-n buttons on a track; mark the chosen one with aria-pressed. */
export const Segmented = styled.div<{ $wrap?: boolean }>`
  display: flex;
  flex-wrap: ${({ $wrap }) => ($wrap ? "wrap" : "nowrap")};
  gap: 4px;
  padding: 4px;
  background: ${({ theme }) => theme.colors.surfaceSunken};
  border-radius: ${({ theme }) => theme.radii.md};
  & > button {
    flex: 1 1 auto;
    min-height: 40px;
    padding: 6px 12px;
    border: 0;
    border-radius: ${({ theme }) => theme.radii.sm};
    background: transparent;
    color: ${({ theme }) => theme.colors.textMuted};
    font-size: ${({ theme }) => theme.fontSizes.md};
    font-weight: 600;
    transition: background-color ${({ theme }) => theme.motion.base}, color ${({ theme }) => theme.motion.base},
      transform ${({ theme }) => theme.motion.fast};
    &:hover { color: ${({ theme }) => theme.colors.textMain}; }
    &:active { transform: scale(.97); }
    &[aria-pressed="true"] {
      background: ${({ theme }) => theme.colors.surface};
      color: ${({ theme }) => theme.colors.primaryStrong};
      box-shadow: ${({ theme }) => theme.shadows.card};
    }
  }
`;

/** Checkbox toggles under a list: "Show past", "Show ignored". */
export const Toggles = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 4px 20px;
  margin: 8px 0 12px;
  font-size: ${({ theme }) => theme.fontSizes.md};
  & > label { min-height: 36px; }
`;
