import { useEffect, useState } from "react";
import { barColors } from "./styles/theme";

// Light/dark switch. "system" follows the device; light/dark override it. Stored per device (index.html applies
// it before the first paint, so there is no flash).
export type Theme = "system" | "light" | "dark";
const KEY = "theme";

export function storedTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  // Both media-specific metas get the same colour, so a forced theme wins over the device's.
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", dark ? barColors.dark : barColors.light));
  // Android colours the installed app's system bars from the manifest, which the server
  // builds from this cookie (see manifest_response in backend/app/main.py).
  try {
    const secure = location.protocol === "https:" ? "; Secure" : "";
    const value = theme === "system" ? "; max-age=0" : `${theme}; max-age=31536000`;
    document.cookie = `theme=${value}; path=/; SameSite=Lax${secure}`;
  } catch {
    /* cookies blocked: the manifest keeps its defaults */
  }
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  useEffect(() => {
    apply(theme);
    try {
      if (theme === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, theme);
    } catch {
      /* private mode: still applies for this visit */
    }
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);
  return [theme, setTheme];
}
