/**
 * Paladex icon set: authored on a 24px grid, 1.6px strokes with square caps
 * (painted court lines). Decorative by default; pass `label` to expose one.
 */
import type { SVGProps } from "react";

const PATHS = {
  search: <><circle cx="10.5" cy="10.5" r="6" /><path d="M15 15l5 5" /></>,
  menu: <path d="M4 7h16M4 12h16M4 17h10" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  chevronDown: <path d="M6 9l6 6 6-6" />,
  chevronUp: <path d="M6 15l6-6 6 6" />,
  chevronLeft: <path d="M15 6l-6 6 6 6" />,
  chevronRight: <path d="M9 6l6 6-6 6" />,
  arrowRight: <path d="M4 12h15M13 6l6 6-6 6" />,
  external: <path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  plus: <path d="M12 5v14M5 12h14" />,
  minus: <path d="M5 12h14" />,
  zoomIn: <><circle cx="10.5" cy="10.5" r="6" /><path d="M15 15l5 5M10.5 8v5M8 10.5h5" /></>,
  zoomOut: <><circle cx="10.5" cy="10.5" r="6" /><path d="M15 15l5 5M8 10.5h5" /></>,
  orbit: <><ellipse cx="12" cy="12" rx="9" ry="4" /><path d="M12 3v18" /><path d="M16.5 4.8l1.6 1.2-1.4 1.4" /></>,
  reset: <><path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" /><path d="M4 4v4.5h4.5" /></>,
  fullscreen: <path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" />,
  fullscreenExit: <path d="M9 4v5H4M20 9h-5V4M15 20v-5h5M4 15h5v5" />,
  play: <path d="M8 5.5l10 6.5-10 6.5z" />,
  pause: <path d="M8 5v14M16 5v14" />,
  eye: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="2.8" /></>,
  eyeOff: <><path d="M4 4l16 16" /><path d="M9.5 6a10 10 0 0 1 2.5-.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-3 3.8M6.2 7.6A17 17 0 0 0 2.5 12S6 18.5 12 18.5a9.6 9.6 0 0 0 4-.9" /></>,
  layers: <path d="M12 4l9 5-9 5-9-5 9-5zM3 14l9 5 9-5" />,
  explode: <path d="M12 2.5v4M12 17.5v4M7 9.5h10v5H7zM4 6.5l3 3M20 6.5l-3 3M4 17.5l3-3M20 17.5l-3-3" />,
  light: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" /></>,
  compare: <path d="M5 4h5v16H5zM14 4h5v16h-5zM10 9h4M10 15h4" />,
  sliders: <path d="M4 7h9M17 7h3M4 17h3M11 17h9M15 5v4M9 15v4" />,
  sort: <path d="M7 4v16M3.5 16.5L7 20l3.5-3.5M17 20V4M13.5 7.5L17 4l3.5 3.5" />,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></>,
  cube: <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3zM4 7.5l8 4.5 8-4.5M12 12v9" />,
  image: <><path d="M4 5h16v14H4z" /><path d="M4 16l5-5 4 4 2.5-2.5L20 17" /><circle cx="15.5" cy="9" r="1.2" /></>,
  bag: <path d="M5 8h14l-1 12H6L5 8zM9 8V6.5a3 3 0 0 1 6 0V8" />,
  warning: <path d="M12 4l9 16H3l9-16zM12 10v4.5M12 17v.5" />,
  link: <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />,
  unlink: <path d="M14.5 6.3l-1-1a4 4 0 0 0-5.7 5.7M9.5 17.7l1 1a4 4 0 0 0 5.7-5.7M4 4l16 16" />,
  trash: <path d="M5 7h14M10 7V4.5h4V7M7 7l1 13h8l1-13" />,
  edit: <path d="M4 20h4l11-11-4-4L4 16v4zM13.5 6.5l4 4" />,
  upload: <path d="M12 16V4M7 9l5-5 5 5M4 16v4h16v-4" />,
  lock: <><path d="M6 11h12v9H6z" /><path d="M8.5 11V8a3.5 3.5 0 0 1 7 0v3" /></>,
  logout: <path d="M10 4H4v16h6M15 8l4 4-4 4M9 12h10" />,
  ruler: <path d="M3 15.5L15.5 3 21 8.5 8.5 21 3 15.5zM7 11.5l2 2M10 8.5l2 2M13 5.5l2 2" />,
  target: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="0.6" /></>,
  balance: <path d="M12 4v16M5 20h14M4 8h16M7 8l-3 6h6l-3-6zM17 8l-3 6h6l-3-6z" />,
  hand: <path d="M8 12V5.5a1.5 1.5 0 0 1 3 0V11M11 10V4.5a1.5 1.5 0 0 1 3 0V11M14 10.5V6a1.5 1.5 0 0 1 3 0v8a6 6 0 0 1-6 6h-.5a6 6 0 0 1-5-2.7L3 13.5a1.6 1.6 0 0 1 2.5-2L8 14" />,
  keyboard: <><path d="M3 6.5h18v11H3z" /><path d="M6.5 10h.5M9.5 10h.5M12.5 10h.5M15.5 10h.5M8 14h8" /></>,
  racket: <><path d="M12 2.8c3.7 0 6.6 2.9 6.6 6.9 0 3.5-2.3 6.4-4.9 7.4l-.7 1.2V21h-2v-2.7l-.7-1.2c-2.6-1-4.9-3.9-4.9-7.4 0-4 2.9-6.9 6.6-6.9z" /><path d="M9.5 8h.5M12 7h.5M14 8.5h.5M10.5 11h.5M13 11.5h.5" /></>,
  court: <><path d="M4 3h16v18H4z" /><path d="M4 12h16M12 6.5v11M4 6.5h16M4 17.5h16" /></>,
  sync: <path d="M4 12a8 8 0 0 1 13.7-5.6M20 12a8 8 0 0 1-13.7 5.6M18 3v4h-4M6 21v-4h4" />,
  ghost: <><path d="M8 4h8v16H8z" opacity="0.45" /><path d="M5 6h8v14H5z" /></>,
  grid: <path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" />,
  arrowLeft: <path d="M20 12H5M11 6l-6 6 6 6" />,
  dot: <circle cx="12" cy="12" r="3" />,
  trophy: <path d="M7 4h10v4a5 5 0 0 1-10 0V4zM7 6H4.5v1A3 3 0 0 0 7.4 10M17 6h2.5v1a3 3 0 0 1-2.9 3M12 13v4M9 20h6M10 17h4v3h-4z" />,
  spark: <path d="M12 3v5M12 16v5M3 12h5M16 12h5M6.5 6.5l2.5 2.5M15 15l2.5 2.5M6.5 17.5L9 15M15 9l2.5-2.5" />,
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({
  name,
  size = 20,
  label,
  strokeWidth = 1.6,
  ...rest
}: { name: IconName; size?: number; label?: string; strokeWidth?: number } & Omit<SVGProps<SVGSVGElement>, "name">) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
      focusable="false"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  );
}
