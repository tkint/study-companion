import { useState } from "react";

// The course's header image from Moodle, or a placeholder drawn from the course itself
// (a colour picked from its id and its initials) when it has none or it fails to load.

function hue(id: number): number {
  return (id * 137.508) % 360; // golden angle: neighbouring ids get distinct colours
}

export function initials(shortname: string, fullname: string): string {
  const words = (fullname || shortname).split(/[\s\-_/.:]+/u).filter((w) => /\p{L}|\p{N}/u.test(w));
  // Skip short words ("and", "de", "of") when there are enough long ones.
  const long = words.filter((w) => w.length > 3);
  const letters = (long.length >= 2 ? long : words).slice(0, 2).map((w) => [...w.replace(/^[^\p{L}\p{N}]+/u, "")][0] ?? "");
  return letters.join("").toUpperCase() || "?";
}

export function CourseCover({ id, shortname, fullname, imageUrl, variant }: {
  id: number;
  shortname: string;
  fullname: string;
  imageUrl: string | null | undefined;
  variant: "thumb" | "banner";
}) {
  const [failed, setFailed] = useState(false);
  const h = hue(id);
  const style = { "--cover-h": `${h}`, "--cover-h2": `${(h + 40) % 360}` } as React.CSSProperties;
  if (imageUrl && !failed) {
    return (
      <div className={`cover cover-${variant}`} style={style}>
        <img src={imageUrl} alt="" loading={variant === "thumb" ? "lazy" : "eager"} decoding="async"
          onError={() => setFailed(true)} />
      </div>
    );
  }
  return (
    <div className={`cover cover-${variant} cover-fallback`} style={style} aria-hidden="true">
      <span>{initials(shortname, fullname)}</span>
    </div>
  );
}
