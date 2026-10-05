import { useEffect, useMemo, useRef } from "react";

import type { CategorizeStatus } from "@/api/client";
import { cn } from "@/lib/utils";

const RINGS = 4;
const VIEW = 100;
const OUTER_R = 45;
// Four tighter rings keep a clear iris while making the whole mark more compact.
const R_STEP = 9.5;
const CX_STEP = 6.25;

type Mode = "idle" | "busy" | "waiting" | "offline";
export type AssistantPresence = "idle" | "listening" | "thinking" | "speaking";

function hash01(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

function modeFromStatus(st: CategorizeStatus | null): Mode {
  if (!st || !st.ollama_reachable) return "offline";
  if (st.phase === "waiting_ollama" && st.queue_remaining > 0) return "waiting";
  if (st.phase === "running" || st.phase === "researching" || st.queue_remaining > 0) return "busy";
  return "idle";
}

function seedFromStatus(st: CategorizeStatus | null): string {
  if (!st) return "idle";
  if (st.current) {
    return `c:${st.current.id}|${st.current.counterparty || ""}|${st.current.amount}`;
  }
  if (st.last_done[0]) {
    return `d:${st.last_done[0].id}|${st.last_done[0].slug}|${st.last_done[0].confidence}`;
  }
  return `p:${st.phase}|q:${st.queue_remaining}`;
}

function ringCx(i: number, look: number): number {
  // All rings follow the gaze. The increasing offset keeps some depth without
  // making the inner iris counter-steer against the surrounding rings.
  return VIEW / 2 - i * CX_STEP * look;
}

function ringCy(i: number, look: number): number {
  // Keep the vertical and horizontal gaze offsets on the same scale. The
  // orbit is meant to be circular; compressing Y here made the eye travel
  // noticeably farther left/right than up/down.
  return VIEW / 2 - i * CX_STEP * look;
}

export function AssistantAvatar({
  status,
  className,
  attention = false,
  engaged = false,
  presence = "idle",
}: {
  status: CategorizeStatus | null;
  className?: string;
  attention?: boolean;
  engaged?: boolean;
  presence?: AssistantPresence;
}) {
  const mode = modeFromStatus(status);
  const seed = useMemo(() => seedFromStatus(status), [status]);
  const targetLook = useMemo(() => {
    const h = hash01(seed);
    // Map hash to roughly -1..1, bias slightly left like the reference
    if (presence === "listening") return 0.55;
    if (presence === "speaking") return 0.08;
    if (attention) return -1.05;
    return (h * 2 - 1) * (mode === "offline" ? 0.35 : 0.95);
  }, [seed, mode, attention, presence]);

  const lookXRef = useRef(0.85);
  const lookYRef = useRef(0);
  const pointerLookRef = useRef({ x: 0, y: 0, active: false });
  const svgRef = useRef<SVGSVGElement | null>(null);
  const ringsRef = useRef<(SVGCircleElement | SVGPathElement | null)[]>([]);
  const rafRef = useRef(0);
  const timerRef = useRef<number | undefined>(undefined);
  const t0Ref = useRef(performance.now());
  const lastTickRef = useRef<number | null>(null);
  const pulsePhaseRef = useRef(0);
  const pulseStrengthRef = useRef(0);

  useEffect(() => {
    t0Ref.current = performance.now();
    lastTickRef.current = null;
  }, [seed]);

  useEffect(() => {
    const media = window.matchMedia("(hover: hover) and (pointer: fine)");
    if (!media.matches) return;

    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect || rect.width === 0 || rect.height === 0) return;
      const eyeCenterX = rect.left + rect.width / 2;
      const eyeCenterY = rect.top + rect.height / 2;
      // The ring geometry offsets the inner iris in the opposite direction;
      // invert both axes so the eye visibly looks toward the cursor.
      pointerLookRef.current = {
        x: Math.max(-1, Math.min(1, -((event.clientX - eyeCenterX) / (window.innerWidth / 2)))),
        y: Math.max(-0.75, Math.min(0.75, -((event.clientY - eyeCenterY) / (window.innerHeight / 2)) * 1.5)),
        active: true,
      };
    };
    const onPointerLeave = () => {
      pointerLookRef.current.active = false;
    };
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("pointerleave", onPointerLeave);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerleave", onPointerLeave);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    const reducedRate = !window.matchMedia("(hover: hover) and (pointer: fine)").matches;

    const scheduleNext = () => {
      if (!alive) return;
      if (reducedRate) {
        timerRef.current = window.setTimeout(() => tick(performance.now()), 33);
      } else {
        rafRef.current = requestAnimationFrame(tick);
      }
    };

    const tick = (now: number) => {
      if (!alive) return;
      const elapsed = (now - t0Ref.current) / 1000;

      let amp = 0.07;
      let freq = 0.42;
      let follow = 0.065;
      if (attention) {
        amp = 0.05;
        freq = 0.5;
        follow = 0.1;
      } else if (engaged) {
        amp = 0.04;
        freq = 0.28;
        follow = 0.09;
      } else if (mode === "busy") {
        amp = 0.1;
        freq = 0.9;
        follow = 0.16;
      } else if (mode === "waiting") {
        amp = 0.06;
        freq = 0.5;
        follow = 0.06;
      } else if (mode === "offline") {
        follow = 0.32;
      }

      // Slow organic glances at rest, focused gaze while listening/speaking,
      // and quicker searching saccades while tools or the model are working.
      const thinkingStep = Math.floor(elapsed / 0.56);
      const searchX = (hash01(`${seed}|think-x:${thinkingStep}`) * 2 - 1) * 1.02;
      const searchY = (hash01(`${seed}|think-y:${thinkingStep}`) * 2 - 1) * 0.7;
      // Automatic categorization gets a clearly readable circular scanning
      // motion. Keep the irregular saccades for actual chat reasoning only.
      const categorizingOrbitPhase = elapsed * 2.15;
      const categorizingOrbitX = Math.cos(categorizingOrbitPhase) * 0.78;
      const categorizingOrbitY = Math.sin(categorizingOrbitPhase) * 0.78;
      const calmOrbitPhase = elapsed * 0.62;
      const calmOrbitX = Math.cos(calmOrbitPhase) * 0.62;
      const calmOrbitY = Math.sin(calmOrbitPhase) * 0.62;
      const wobble = Math.sin(elapsed * Math.PI * 2 * freq) * amp;
      const stutter =
        mode === "waiting" ? Math.sin(elapsed * 7) * 0.04 : 0;
      // Keep busy motion circular as well: activity changes the radius of the
      // orbit instead of adding a horizontal-only offset.
      const busyRadius = 1 + (wobble + stutter) * 0.55;
      const presenceX = presence === "thinking"
        ? searchX
        : presence === "listening"
          ? 0.62
          : presence === "speaking"
            ? Math.sin(elapsed * 1.7) * 0.1
            : mode === "busy"
              ? categorizingOrbitX * busyRadius
              : calmOrbitX;
      const presenceY = presence === "thinking"
        ? searchY
        : presence === "listening"
          ? 0.52
          : presence === "speaking"
            ? Math.sin(elapsed * 1.25) * 0.08
            : mode === "busy"
              ? categorizingOrbitY * busyRadius
              : calmOrbitY;
      if (presence === "thinking") follow = 0.16;
      if (presence === "listening") follow = 0.11;
      if (presence === "speaking") follow = 0.08;

      const desiredX = Math.max(
        -1.15,
        Math.min(
          1.15,
          mode !== "busy" && pointerLookRef.current.active
              ? pointerLookRef.current.x
            : presenceX,
        )
      );
      const desiredY = Math.max(
        -0.82,
        Math.min(
          0.82,
          mode !== "busy" && pointerLookRef.current.active
              ? pointerLookRef.current.y
              : presenceY,
        )
      );
      lookXRef.current += (desiredX - lookXRef.current) * follow;
      lookYRef.current += (desiredY - lookYRef.current) * follow;

      const lookX = lookXRef.current;
      const lookY = lookYRef.current;
      const waveSpeed = presence === "speaking"
        ? 5.2
        : presence === "thinking"
          ? 3.8
          : mode === "busy"
            ? 4.4
            : mode === "waiting"
              ? 3
              : 1.8;
      const targetStrength = presence === "speaking"
        ? 2.65
        : presence === "thinking"
          ? 1.35
          : mode === "busy"
            ? 1.8
            : mode === "waiting"
              ? 0.55
              : 0;
      const delta = lastTickRef.current == null
        ? 0
        : Math.min(0.05, Math.max(0, (now - lastTickRef.current) / 1000));
      lastTickRef.current = now;
      // Integrate the phase instead of deriving it from elapsed * speed. If
      // the presence changes, the wave then keeps moving continuously rather
      // than jumping to a new phase.
      pulsePhaseRef.current += delta * waveSpeed;
      pulseStrengthRef.current +=
        (targetStrength - pulseStrengthRef.current) * Math.min(1, delta * 5.5);
      for (let i = 0; i < RINGS; i++) {
        const el = ringsRef.current[i];
        if (!el) continue;
        const distanceFromIris = RINGS - 1 - i;
        const wave = Math.max(
          0,
          Math.sin(pulsePhaseRef.current - distanceFromIris * 0.5)
        ) ** 5;
        const strength = pulseStrengthRef.current;
        const baseRadius = OUTER_R - i * R_STEP;
        el.setAttribute("cx", String(ringCx(i, lookX)));
        el.setAttribute("cy", String(ringCy(i, lookY)));
        el.setAttribute("r", String(baseRadius + (i === 0 ? 0 : wave * strength)));
      }

      scheduleNext();
    };

    scheduleNext();
    return () => {
      alive = false;
      cancelAnimationFrame(rafRef.current);
      if (timerRef.current !== undefined) window.clearTimeout(timerRef.current);
      timerRef.current = undefined;
    };
  }, [targetLook, mode, attention, engaged, presence, seed]);

  return (
    <svg
      ref={svgRef}
      viewBox="-4 -4 108 108"
      fill="none"
      aria-hidden
      className={cn(
        "h-8 w-8 shrink-0 text-foreground transition-opacity dark:text-white",
        mode === "offline" && "opacity-85",
        mode === "waiting" && "opacity-85",
        className
      )}
    >
      {Array.from({ length: RINGS }, (_, i) => (
        <circle
          key={i}
          ref={(el) => { ringsRef.current[i] = el; }}
          cx={ringCx(i, lookXRef.current)}
          cy={ringCy(i, lookYRef.current)}
          r={OUTER_R - i * R_STEP}
          stroke="currentColor"
          strokeWidth={mode === "busy" ? 1.15 : 1}
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}
