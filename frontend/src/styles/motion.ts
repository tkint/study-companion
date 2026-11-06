import { keyframes } from "styled-components";

// Small, friendly movements. All of them stop with "reduce motion" (see GlobalStyle).

export const rise = keyframes`
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: none; }
`;

export const pop = keyframes`
  0% { opacity: 0; transform: scale(.6); }
  100% { opacity: 1; transform: scale(1); }
`;

export const hop = keyframes`
  0%, 100% { transform: none; }
  40% { transform: translateY(-3px); }
`;

export const spin = keyframes`
  to { transform: rotate(360deg); }
`;

export const fadeIn = keyframes`
  from { opacity: 0; }
  to { opacity: 1; }
`;

export const slideUp = keyframes`
  from { opacity: 0; transform: translateY(24px); }
  to { opacity: 1; transform: none; }
`;

/** Delay for the n-th item of a list that slides in, capped so long lists don't lag. */
export const stagger = (step = 40, max = 4) => `
  &:nth-child(2) { animation-delay: ${step}ms; }
  &:nth-child(3) { animation-delay: ${step * 2}ms; }
  &:nth-child(4) { animation-delay: ${step * 3}ms; }
  &:nth-child(n+5) { animation-delay: ${step * max}ms; }
`;
