import styled, { css } from "styled-components";
import type { Route } from "../router";
import { sectionOf } from "../nav";

// The pages of the current section, under the top bar: "Overview · Catch-up plan · Schedule".
// Shown only for sections with more than one page, so you always see where you are and what
// sits next to it. Scrolls sideways on a narrow phone instead of wrapping.

const Bar = styled.nav`
  display: flex;
  gap: 6px;
  margin: -8px 0 20px;
  padding: 4px;
  width: fit-content;
  max-width: 100%;
  overflow-x: auto;
  scrollbar-width: none;
  border-radius: ${({ theme }) => theme.radii.pill};
  background: ${({ theme }) => theme.colors.surfaceSunken};
  &::-webkit-scrollbar { display: none; }
`;

const Item = styled.a<{ $active: boolean }>`
  flex: none;
  display: inline-flex;
  align-items: center;
  min-height: 36px;
  padding: 6px 14px;
  border-radius: ${({ theme }) => theme.radii.pill};
  font-size: ${({ theme }) => theme.fontSizes.md};
  font-weight: 650;
  white-space: nowrap;
  color: ${({ theme }) => theme.colors.textMuted};
  transition: background-color ${({ theme }) => theme.motion.base}, color ${({ theme }) => theme.motion.base};
  &:hover { text-decoration: none; color: ${({ theme }) => theme.colors.textMain}; }
  ${({ $active, theme }) =>
    $active &&
    css`
      color: ${theme.colors.primaryStrong};
      background: ${theme.colors.surface};
      box-shadow: ${theme.shadows.card};
      &:hover { color: ${theme.colors.primaryStrong}; }
    `}
`;

export function SectionNav({ route }: { route: Route }) {
  const section = sectionOf(route.name);
  if (section.pages.length < 2) return null;
  // A study session (one course or due cards) is still "Flashcards".
  const current = section.pages.find((p) => p.route === route.name)?.route;
  return (
    <Bar aria-label={`${section.label} pages`} data-tour="subnav">
      {section.pages.map((p) => (
        <Item key={p.route} href={p.href} title={p.hint} $active={p.route === current}
          aria-current={p.route === current ? "page" : undefined}>
          {p.label}
        </Item>
      ))}
    </Bar>
  );
}
