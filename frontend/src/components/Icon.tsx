// Small hand-made line icons (24x24, stroke = currentColor), so the app needs no icon library.

const PATHS = {
  flame: "M12 3c1 3.5 5 5.5 5 10a5 5 0 01-10 0c0-2 1-3.5 2-4.5 0 1.5.8 2.5 2 3 0-3.5-1-5.5 1-8.5z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  checkCircle: "M12 21a9 9 0 100-18 9 9 0 000 18zM8 12.5l2.8 2.8L16.5 9.5",
  book: "M4 5.5A2.5 2.5 0 016.5 3H20v15H6.5A2.5 2.5 0 004 20.5zM4 20.5A2.5 2.5 0 016.5 23H20v-5",
  cards: "M8 4h11a1 1 0 011 1v11M4 8h11a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V9a1 1 0 011-1z",
  trophy: "M8 4h8v5a4 4 0 01-8 0zM8 6H5a3 3 0 003 4M16 6h3a3 3 0 01-3 4M12 13v4M8.5 21h7M9.5 17h5v4h-5z",
  sparkles: "M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6zM18.5 14l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8zM5 15l.6 1.4L7 17l-1.4.6L5 19l-.6-1.4L3 17l1.4-.6z",
  calendar: "M4 6h16v14H4zM4 10h16M9 3v5M15 3v5",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
  target: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 17a5 5 0 100-10 5 5 0 000 10zM12 13a1 1 0 100-2 1 1 0 000 2z",
  note: "M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h5",
  sun: "M12 17a5 5 0 100-10 5 5 0 000 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z",
  sunrise: "M4 18h16M12 4v4M5.6 9.6l1.4 1.4M18.4 9.6L17 11M7 18a5 5 0 0110 0M2 22h20",
  refresh: "M20 11a8 8 0 00-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0014.3 4.9L20 16M20 20v-4h-4",
  arrow: "M5 12h14M13 6l6 6-6 6",
  leaf: "M5 19c0-8 5-14 15-14 0 10-6 15-14 15M5 19l7-7",
  heart: "M12 20s-7-4.4-7-10a4 4 0 017-2.6A4 4 0 0119 10c0 5.6-7 10-7 10z",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, className, size }: { name: IconName; className?: string; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" className={`icon${className ? ` ${className}` : ""}`} aria-hidden="true"
      width={size} height={size}>
      <path d={PATHS[name]} />
    </svg>
  );
}
