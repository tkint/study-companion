// A small confetti burst on a canvas laid over the page, for little wins (a deadline done, a
// section studied, a review session finished). No library: about 80 particles for ~1.8 s,
// then the canvas is removed. With "reduce motion" on, nothing flies; the caller's own
// feedback (the button turning into "Done") is enough.

// The palette's accents (src/styles/theme.ts).
const COLORS = ["#3B82F6", "#F59E0B", "#10B981", "#0EA5E9", "#F97316", "#FBBF24"];

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  rot: number;
  vr: number;
  color: string;
  round: boolean;
}

function reducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Burst from an element (its centre) or from the middle of the screen. */
export function celebrate(from?: Element | null, amount = 50): void {
  if (reducedMotion() || typeof document === "undefined") return;
  const rect = from?.getBoundingClientRect();
  const ox = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
  const oy = rect ? rect.top + rect.height / 2 : window.innerHeight / 3;

  const canvas = document.createElement("canvas");
  canvas.style.cssText = "position:fixed;inset:0;width:100vw;height:100vh;pointer-events:none;z-index:100";
  canvas.setAttribute("aria-hidden", "true");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = window.innerWidth * dpr;
  canvas.height = window.innerHeight * dpr;
  document.body.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    canvas.remove();
    return;
  }
  ctx.scale(dpr, dpr);

  const parts: Particle[] = Array.from({ length: amount }, () => {
    const angle = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 1.1;
    const speed = 5 + Math.random() * 7;
    return {
      x: ox,
      y: oy,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      size: 5 + Math.random() * 5,
      rot: Math.random() * Math.PI,
      vr: (Math.random() - 0.5) * 0.4,
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
      round: Math.random() < 0.35,
    };
  });

  const start = performance.now();
  const duration = 1800;
  function frame(t: number) {
    const elapsed = t - start;
    ctx!.clearRect(0, 0, window.innerWidth, window.innerHeight);
    ctx!.globalAlpha = Math.max(0, 1 - Math.max(0, elapsed - duration * 0.6) / (duration * 0.4));
    for (const p of parts) {
      p.vy += 0.25; // gravity
      p.vx *= 0.985;
      p.vy *= 0.985;
      p.x += p.vx;
      p.y += p.vy;
      p.rot += p.vr;
      ctx!.save();
      ctx!.translate(p.x, p.y);
      ctx!.rotate(p.rot);
      ctx!.fillStyle = p.color;
      if (p.round) {
        ctx!.beginPath();
        ctx!.arc(0, 0, p.size / 2.4, 0, Math.PI * 2);
        ctx!.fill();
      } else {
        ctx!.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
      }
      ctx!.restore();
    }
    if (elapsed < duration) requestAnimationFrame(frame);
    else canvas.remove();
  }
  requestAnimationFrame(frame);
}
