import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { ChartPie, LayoutDashboard, LockKeyhole, MessageCircle, Moon, ReceiptText, Sun, UserRound } from "lucide-react";

import { api, type CategorizeStatus } from "@/api/client";
import { useAppSetup } from "@/auth/AppSetupContext";
import { useVault } from "@/auth/VaultContext";
import { AssistantAvatar, type AssistantPresence } from "@/components/AssistantAvatar";
import { LanguageSwitch } from "@/components/LanguageSwitch";
import { SyncProgressModal } from "@/components/SyncProgressModal";
import { Button } from "@/components/ui";
import { applyTheme, getStoredTheme, toggleTheme, type ThemeMode } from "@/lib/theme";
import { isDemoModeEnabled, setDemoModeEnabled, scaleDemoMoney } from "@/lib/demo";
import { cn } from "@/lib/utils";

type Translate = (key: string, options?: Record<string, unknown>) => string;

type FlowPoint = [number, number];
/**
 * Create a second, very quiet layer of filled stream ribbons. These are not
 * animated per shape; two concatenated paths are moved as a whole in CSS.
 * That gives the background the broad, liquid bands from a topographic flow
 * map while keeping the paint cost small on mobile devices.
 */
function createOrganicRibbons(count: number, phase: number, seed: number): string {
  const random = (() => {
    let state = seed >>> 0;
    return () => {
      state = (state * 1664525 + 1013904223) >>> 0;
      return state / 4294967296;
    };
  })();
  const width = 1200;
  const height = 900;
  const tau = Math.PI * 2;
  const sampleCount = 20;

  const smoothClosedPath = (points: FlowPoint[]) => {
    if (points.length < 3) return "";
    const midpoint = (first: FlowPoint, second: FlowPoint): FlowPoint => [
      (first[0] + second[0]) / 2,
      (first[1] + second[1]) / 2,
    ];
    const startingPoint = midpoint(points[points.length - 1], points[0]);
    let path = `M ${startingPoint[0].toFixed(1)} ${startingPoint[1].toFixed(1)}`;
    for (let index = 0; index < points.length; index += 1) {
      const current = points[index];
      const next = points[(index + 1) % points.length];
      const endpoint = midpoint(current, next);
      // A quadratic B-spline passes through the midpoint between samples.
      // The incoming and outgoing derivatives at each join are identical,
      // so the closed contour remains C1-continuous without visible corners.
      path += ` Q ${current[0].toFixed(1)} ${current[1].toFixed(1)} ${endpoint[0].toFixed(1)} ${endpoint[1].toFixed(1)}`;
    }
    return `${path} Z`;
  };

  const ribbons: string[] = [];
  for (let ribbonIndex = 0; ribbonIndex < count; ribbonIndex += 1) {
    const originX = (random() * 1.2 - 0.1) * width;
    const originY = (random() * 1.2 - 0.1) * height;
    const angle = random() * tau;
    const length = 240 + random() * 500;
    const sway = 70 + random() * 170;
    const turns = 0.45 + random() * 1.15;
    const ribbonWidth = 24 + random() * 46;
    const phaseOffset = phase + random() * tau;
    const directionX = Math.cos(angle);
    const directionY = Math.sin(angle);
    const normalX = -directionY;
    const normalY = directionX;
    const centerline: FlowPoint[] = [];
    const halfWidths: number[] = [];

    for (let index = 0; index < sampleCount; index += 1) {
      const progress = index / (sampleCount - 1);
      const distance = (progress - 0.5) * length;
      const swirl = Math.sin(progress * tau * turns + phaseOffset) * sway;
      const bow = Math.sin(progress * Math.PI) * Math.cos(phaseOffset * 0.7) * sway * 0.42;
      const x = originX + directionX * distance + normalX * (swirl + bow);
      const y = originY + directionY * distance + normalY * (swirl + bow);
      centerline.push([x, y]);

      // Taper the ends so the filled ribbon reads as a soft, rounded stroke.
      const taper = 0.58 + 0.42 * Math.sin(progress * Math.PI);
      const breathing = 0.9 + 0.1 * Math.sin(progress * tau * 1.4 + phaseOffset);
      halfWidths.push(ribbonWidth * taper * breathing);
    }

    const left: FlowPoint[] = [];
    const right: FlowPoint[] = [];
    centerline.forEach((point, index) => {
      const previous = centerline[Math.max(0, index - 1)];
      const next = centerline[Math.min(centerline.length - 1, index + 1)];
      const tangentX = next[0] - previous[0];
      const tangentY = next[1] - previous[1];
      const tangentLength = Math.hypot(tangentX, tangentY) || 1;
      const localNormalX = -tangentY / tangentLength;
      const localNormalY = tangentX / tangentLength;
      left.push([
        point[0] + localNormalX * halfWidths[index],
        point[1] + localNormalY * halfWidths[index],
      ]);
      right.push([
        point[0] - localNormalX * halfWidths[index],
        point[1] - localNormalY * halfWidths[index],
      ]);
    });

    const path = smoothClosedPath([...left, ...right.reverse()]);
    if (path) ribbons.push(path);
  }

  return ribbons.join(" ");
}

type IsolineLandscape = {
  bands: string[];
};

type ContourPoint = {
  key: string;
  point: FlowPoint;
};

type ContourSegment = {
  a: ContourPoint;
  b: ContourPoint;
};

/**
 * Build a small contour map from a seeded scalar field. The marching-squares
 * pass runs once at module load, then the browser only paints a handful of
 * filled SVG paths. Each band is the area between two neighbouring height
 * levels; the contour paths are kept separately for the thin isoline edges.
 */
function createIsolineLandscape(seed: number, phase: number): IsolineLandscape {
  const random = (() => {
    let state = seed >>> 0;
    return () => {
      state = (state * 1664525 + 1013904223) >>> 0;
      return state / 4294967296;
    };
  })();
  const width = 1200;
  const height = 900;
  const columns = 96;
  const rows = 72;
  const tau = Math.PI * 2;
  const levels = [0.29, 0.42, 0.55, 0.68, 0.81];
  const offsets = Array.from({ length: 4 }, () => random() * tau);
  const hills = Array.from({ length: 4 }, () => ({
    x: random() * 1.02 - 0.01,
    y: random() * 1.02 - 0.01,
    radius: 0.16 + random() * 0.2,
    strength: (random() - 0.5) * 0.3,
  }));

  const rawValues: number[][] = [];
  let minimum = Number.POSITIVE_INFINITY;
  let maximum = Number.NEGATIVE_INFINITY;
  for (let row = 0; row <= rows; row += 1) {
    const values: number[] = [];
    const y = row / rows;
    for (let column = 0; column <= columns; column += 1) {
      const x = column / columns;
      // Warp the sampling coordinates before evaluating the field. This
      // creates broad, meandering folds instead of a clean tiled-noise look.
      const warpedX =
        x +
        0.018 * Math.sin(tau * (0.52 * x + 0.74 * y) + phase + offsets[1]) +
        0.008 * Math.cos(tau * (1.15 * x - 0.42 * y) + offsets[3]);
      const warpedY =
        y +
        0.022 * Math.cos(tau * (0.74 * x - 0.48 * y) + phase * 0.8 + offsets[2]) -
        0.009 * Math.sin(tau * (1.12 * x + 0.96 * y) + offsets[0]);
      let value =
        0.5 +
        0.24 * Math.sin(tau * (0.88 * warpedX + 0.54 * warpedY) + phase + offsets[0]) +
        0.15 * Math.cos(tau * (0.46 * warpedX - 0.72 * warpedY) + offsets[1]) +
        0.06 * Math.sin(tau * (1.48 * warpedX + 1.12 * warpedY) + offsets[2]) +
        0.025 * Math.cos(tau * (2.45 * warpedX - 1.85 * warpedY) + offsets[3]);
      hills.forEach(({ x: hillX, y: hillY, radius, strength }) => {
        const distanceX = warpedX - hillX;
        const distanceY = warpedY - hillY;
        value += strength * Math.exp(-((distanceX * distanceX + distanceY * distanceY) / (radius * radius)));
      });
      values.push(value);
      minimum = Math.min(minimum, value);
      maximum = Math.max(maximum, value);
    }
    rawValues.push(values);
  }

  const values = rawValues.map((row, rowIndex) => row.map((raw, columnIndex) => {
    const normalized = (raw - minimum) / Math.max(0.0001, maximum - minimum);
    const x = columnIndex / columns;
    const y = rowIndex / rows;
    const edgeDistance = Math.min(x, y, 1 - x, 1 - y);
    const edgeProgress = Math.min(1, edgeDistance / 0.19);
    const edgeMask = edgeProgress * edgeProgress * (3 - 2 * edgeProgress);
    // Keep the outer frame in the lowlands so the higher isolines form
    // closed islands instead of leaving open paths at the SVG boundary.
    return normalized * (0.2 + edgeMask * 0.8);
  }));

  const smoothClosedPath = (points: FlowPoint[]) => {
    if (points.length < 3) return "";
    const midpoint = (first: FlowPoint, second: FlowPoint): FlowPoint => [
      (first[0] + second[0]) / 2,
      (first[1] + second[1]) / 2,
    ];
    const startingPoint = midpoint(points[points.length - 1], points[0]);
    let path = `M ${startingPoint[0].toFixed(1)} ${startingPoint[1].toFixed(1)}`;
    for (let index = 0; index < points.length; index += 1) {
      const current = points[index];
      const next = points[(index + 1) % points.length];
      const endpoint = midpoint(current, next);
      // A quadratic B-spline passes through the midpoint between samples.
      // The incoming and outgoing derivatives at each join are identical,
      // so the closed contour remains C1-continuous without visible corners.
      path += ` Q ${current[0].toFixed(1)} ${current[1].toFixed(1)} ${endpoint[0].toFixed(1)} ${endpoint[1].toFixed(1)}`;
    }
    return `${path} Z`;
  };

  const chaikinSmooth = (points: FlowPoint[], iterations: number) => {
    let smoothed = points;
    for (let iteration = 0; iteration < iterations; iteration += 1) {
      const next: FlowPoint[] = [];
      for (let index = 0; index < smoothed.length; index += 1) {
        const current = smoothed[index];
        const following = smoothed[(index + 1) % smoothed.length];
        next.push([
          current[0] * 0.75 + following[0] * 0.25,
          current[1] * 0.75 + following[1] * 0.25,
        ]);
        next.push([
          current[0] * 0.25 + following[0] * 0.75,
          current[1] * 0.25 + following[1] * 0.75,
        ]);
      }
      smoothed = next;
    }
    return smoothed;
  };

  const interpolate = (first: number, second: number, level: number) => {
    if (Math.abs(second - first) < 0.0001) return 0.5;
    return Math.max(0, Math.min(1, (level - first) / (second - first)));
  };

  const contours = levels.map((level) => {
    const segments: ContourSegment[] = [];
    const cellWidth = width / columns;
    const cellHeight = height / rows;

    const edgePoint = (
      edge: "top" | "right" | "bottom" | "left",
      column: number,
      row: number,
      topLeft: number,
      topRight: number,
      bottomRight: number,
      bottomLeft: number
    ): ContourPoint => {
      if (edge === "top") {
        const progress = interpolate(topLeft, topRight, level);
        return {
          key: `h:${column}:${row}`,
          point: [(column + progress) * cellWidth, row * cellHeight],
        };
      }
      if (edge === "right") {
        const progress = interpolate(topRight, bottomRight, level);
        return {
          key: `v:${column + 1}:${row}`,
          point: [(column + 1) * cellWidth, (row + progress) * cellHeight],
        };
      }
      if (edge === "bottom") {
        const progress = interpolate(bottomLeft, bottomRight, level);
        return {
          key: `h:${column}:${row + 1}`,
          point: [(column + progress) * cellWidth, (row + 1) * cellHeight],
        };
      }
      const progress = interpolate(topLeft, bottomLeft, level);
      return {
        key: `v:${column}:${row}`,
        point: [column * cellWidth, (row + progress) * cellHeight],
      };
    };

    for (let row = 0; row < rows; row += 1) {
      for (let column = 0; column < columns; column += 1) {
        const topLeft = values[row][column];
        const topRight = values[row][column + 1];
        const bottomRight = values[row + 1][column + 1];
        const bottomLeft = values[row + 1][column];
        const mask =
          (topLeft >= level ? 1 : 0) |
          (topRight >= level ? 2 : 0) |
          (bottomRight >= level ? 4 : 0) |
          (bottomLeft >= level ? 8 : 0);
        const points = {
          top: edgePoint("top", column, row, topLeft, topRight, bottomRight, bottomLeft),
          right: edgePoint("right", column, row, topLeft, topRight, bottomRight, bottomLeft),
          bottom: edgePoint("bottom", column, row, topLeft, topRight, bottomRight, bottomLeft),
          left: edgePoint("left", column, row, topLeft, topRight, bottomRight, bottomLeft),
        };
        const addSegment = (first: keyof typeof points, second: keyof typeof points) => {
          const a = points[first];
          const b = points[second];
          if (a.key !== b.key) segments.push({ a, b });
        };
        switch (mask) {
          case 1: addSegment("top", "left"); break;
          case 2: addSegment("top", "right"); break;
          case 3: addSegment("left", "right"); break;
          case 4: addSegment("right", "bottom"); break;
          case 5:
            if ((topLeft + topRight + bottomRight + bottomLeft) / 4 >= level) {
              addSegment("top", "right");
              addSegment("bottom", "left");
            } else {
              addSegment("top", "left");
              addSegment("right", "bottom");
            }
            break;
          case 6: addSegment("top", "bottom"); break;
          case 7: addSegment("bottom", "left"); break;
          case 8: addSegment("bottom", "left"); break;
          case 9: addSegment("top", "bottom"); break;
          case 10:
            if ((topLeft + topRight + bottomRight + bottomLeft) / 4 >= level) {
              addSegment("top", "left");
              addSegment("right", "bottom");
            } else {
              addSegment("top", "right");
              addSegment("bottom", "left");
            }
            break;
          case 11: addSegment("right", "bottom"); break;
          case 12: addSegment("right", "left"); break;
          case 13: addSegment("top", "right"); break;
          case 14: addSegment("top", "left"); break;
          default: break;
        }
      }
    }

    const adjacency = new Map<string, number[]>();
    segments.forEach((segment, index) => {
      [segment.a.key, segment.b.key].forEach((key) => {
        const linked = adjacency.get(key);
        if (linked) linked.push(index);
        else adjacency.set(key, [index]);
      });
    });

    const used = new Set<number>();
    const paths: string[] = [];
    segments.forEach((segment, segmentIndex) => {
      if (used.has(segmentIndex)) return;
      const startKey = segment.a.key;
      const points: FlowPoint[] = [segment.a.point];
      let currentKey = startKey;
      let currentSegmentIndex = segmentIndex;
      let closed = false;
      for (let step = 0; step <= segments.length; step += 1) {
        if (used.has(currentSegmentIndex)) break;
        const currentSegment = segments[currentSegmentIndex];
        used.add(currentSegmentIndex);
        const startsAtA = currentSegment.a.key === currentKey;
        const nextPoint = startsAtA ? currentSegment.b : currentSegment.a;
        currentKey = nextPoint.key;
        points.push(nextPoint.point);
        if (currentKey === startKey) {
          closed = true;
          break;
        }
        const nextSegment = adjacency.get(currentKey)?.find((index) => !used.has(index));
        if (nextSegment === undefined) break;
        currentSegmentIndex = nextSegment;
      }
      if (closed && points.length > 3) {
        points.pop();
        const path = smoothClosedPath(chaikinSmooth(points, points.length > 18 ? 2 : 1));
        if (path) paths.push(path);
      }
    });

    return paths.join(" ");
  });

  return {
    bands: levels.map((_, index) => `${contours[index]} ${contours[index + 1] || ""}`.trim()),
  };
}

const AMBIENT_RIBBONS_BACK = createOrganicRibbons(18, 0.45, 0x7a4f21d3);
const AMBIENT_RIBBONS_FRONT = createOrganicRibbons(12, 2.15, 0x2c8d9e71);
const AMBIENT_ISOLINE_PRIMARY = createIsolineLandscape(0x48a1e72b, 0.35);
const AMBIENT_ISOLINE_SECONDARY = createIsolineLandscape(0x93d04f61, 2.4);

export type LayoutOutletContext = {
  assistant: CategorizeStatus | null;
  setChatPresence: (presence: AssistantPresence) => void;
  demoMode: boolean;
  setDemoMode: (enabled: boolean) => void;
};

function assistantHover(st: CategorizeStatus, t: Translate, demoMode = false): string {
  const parts: string[] = [];
  if (!st.ollama_reachable) {
    parts.push(st.message || t("categorize.ollamaUnreachable"));
  }
  if ((st.phase === "running" || st.phase === "researching") && st.current) {
    const currentAmount = demoMode ? scaleDemoMoney(st.current.amount) : st.current.amount;
    parts.push(
      st.phase === "researching"
        ? `${t("categorize.researching")} · ${st.current.counterparty || "—"}`
        : t("categorize.current", {
            label: `${st.current.counterparty || "—"} (${currentAmount ?? "—"})`,
            remaining: st.queue_remaining,
            done: st.queue_processed,
          })
    );
  }
  if (st.last_done.length > 0) {
    parts.push(
      t("categorize.lastDone", {
        items: st.last_done.map((d) => `${d.slug}`).join(", "),
      })
    );
  }
  if (parts.length === 0) {
    return st.ollama_reachable ? t("layout.assistantOnline") : t("layout.assistantOffline");
  }
  return parts.join(" · ");
}

export function Layout() {
  const { t } = useTranslation();
  const location = useLocation();
  const { lock } = useVault();
  const { hasAccounts } = useAppSetup();
  const [theme, setTheme] = useState<ThemeMode>(() => getStoredTheme());
  const [assistant, setAssistant] = useState<CategorizeStatus | null>(null);
  const [chatPresence, setChatPresence] = useState<AssistantPresence>("idle");
  const [seenActivity, setSeenActivity] = useState<string | null>(null);
  const [demoMode, setDemoModeState] = useState(() => isDemoModeEnabled());

  const setDemoMode = (enabled: boolean) => {
    setDemoModeEnabled(enabled);
    setDemoModeState(enabled);
  };

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = () => {
      api
        .categorizeStatus()
        .then((st) => {
          if (cancelled) return;
          setAssistant((current) =>
            current && JSON.stringify(current) === JSON.stringify(st) ? current : st
          );
          const active =
            st.phase === "running" || st.phase === "researching" || st.phase === "waiting_ollama" || st.queue_remaining > 0;
          timer = window.setTimeout(tick, active ? 2500 : 15000);
        })
        .catch(() => {
          if (cancelled) return;
          setAssistant(null);
          timer = window.setTimeout(tick, 15000);
        });
    };

    tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  const links = [
    { to: "/", labelKey: "nav.dashboard", icon: LayoutDashboard },
    { to: "/transactions", labelKey: "nav.transactions", icon: ReceiptText },
    { to: "/chat", labelKey: "nav.chat", icon: MessageCircle },
    { to: "/assets", labelKey: "nav.assets", icon: ChartPie },
    { to: "/profile", labelKey: "nav.profile", icon: UserRound },
  ] as const;
  const managementRoute = ["/accounts", "/connections", "/categories"].includes(location.pathname);

  const activitySignature = assistant?.last_done.map((item) => item.id).join(",") || null;
  const hasAgentAttention = Boolean(activitySignature && activitySignature !== seenActivity);

  const chatActive = location.pathname === "/chat";

  useEffect(() => {
    if (chatActive) setSeenActivity(activitySignature);
  }, [activitySignature, chatActive]);

  return (
    <div
      className={cn(
        "relative mx-auto flex max-w-6xl flex-col px-3 py-3 text-foreground sm:min-h-screen sm:gap-5 sm:overflow-visible sm:px-4 sm:py-5 md:gap-8 md:px-8 md:py-8",
        chatActive
          ? "h-dvh min-h-0 gap-3 overflow-hidden overscroll-none"
          : "min-h-screen gap-5"
      )}
    >
      <div className="ambient-structure" aria-hidden="true">
        <span className="ambient-structure__orb ambient-structure__orb--one" />
        <span className="ambient-structure__orb ambient-structure__orb--two" />
        <svg
          className="ambient-structure__terrain"
          viewBox="0 0 1200 900"
          preserveAspectRatio="xMidYMid slice"
          role="presentation"
        >
          <g className="ambient-structure__isoline-landscape ambient-structure__isoline-landscape--primary">
            {AMBIENT_ISOLINE_PRIMARY.bands.map((path, index) => (
              <path
                key={`ambient-primary-band-${index}`}
                className={`ambient-structure__isoband ambient-structure__isoband--${index}`}
                d={path}
                fillRule="evenodd"
              />
            ))}
          </g>
          <g className="ambient-structure__isoline-landscape ambient-structure__isoline-landscape--secondary">
            {AMBIENT_ISOLINE_SECONDARY.bands.map((path, index) => (
              <path
                key={`ambient-secondary-band-${index}`}
                className={`ambient-structure__isoband ambient-structure__isoband--${index}`}
                d={path}
                fillRule="evenodd"
              />
            ))}
          </g>
          <g className="ambient-structure__ribbon-set ambient-structure__ribbon-set--back">
            <path d={AMBIENT_RIBBONS_BACK} />
          </g>
          <g className="ambient-structure__ribbon-set ambient-structure__ribbon-set--front">
            <path d={AMBIENT_RIBBONS_FRONT} />
          </g>
        </svg>
      </div>
      <SyncProgressModal />
      <header className="glass-header flex items-center justify-between gap-3 rounded-[1.35rem] px-3 py-2.5 sm:rounded-[1.6rem] sm:px-4 sm:py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <NavLink
            to="/chat"
            className={cn(
              "-m-1 rounded-full p-1 outline-none transition hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring/50",
              !hasAccounts && "opacity-60",
            )}
            aria-label={t("agent.open")}
            title={
              hasAccounts
                ? assistant
                  ? assistantHover(assistant, t as Translate, demoMode)
                  : undefined
                : t("agent.noAccountsTitle")
            }
          >
            <AssistantAvatar
              status={assistant}
              attention={hasAgentAttention && !chatActive}
              engaged={chatActive}
              presence={chatActive ? chatPresence : "idle"}
              className="h-9 w-9"
            />
          </NavLink>
          <h1 className="brand-wordmark truncate text-[1.7rem] font-bold tracking-[-0.025em] text-foreground sm:text-[2rem]">
            finsight
          </h1>
          {demoMode && (
            <span className="inline-flex rounded-full bg-warning/15 px-2 py-1 text-[0.58rem] font-semibold uppercase tracking-[0.1em] text-warning sm:text-[0.62rem] sm:tracking-[0.12em]">
              Demo
            </span>
          )}
        </div>
        <nav className="hidden min-w-0 flex-1 items-center justify-center gap-1 sm:flex" aria-label="Hauptnavigation">
          {links.map((link) => {
            const Icon = link.icon;
            return (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.to === "/"}
                className={({ isActive }) => cn(
                  "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition",
                  (isActive || (link.to === "/profile" && managementRoute))
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                  link.to === "/chat" && !hasAccounts && "opacity-60"
                )}
                title={link.to === "/chat" && !hasAccounts ? t("agent.noAccountsTitle") : undefined}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden />
                <span>{t(link.labelKey)}</span>
              </NavLink>
            );
          })}
        </nav>
        <div className="flex shrink-0 items-center gap-1.5">
            <LanguageSwitch className="h-9 px-2.5" />
            <Button
              variant="outline"
              className="h-9 w-9 rounded-full p-0"
              onClick={() => setTheme(toggleTheme())}
              aria-label={t("theme.toggle")}
              title={theme === "dark" ? t("theme.light") : t("theme.dark")}
            >
              {theme === "dark" ? (
                <Sun className="h-4 w-4" aria-hidden />
              ) : (
                <Moon className="h-4 w-4" aria-hidden />
              )}
            </Button>
            <Button
              variant="outline"
              className="h-9 w-9 rounded-full p-0"
              onClick={() => void lock()}
              aria-label={t("vault.lock")}
              title={t("vault.lock")}
            >
              <LockKeyhole className="h-4 w-4" aria-hidden />
            </Button>
        </div>
      </header>
      <nav className="mobile-dock grid grid-cols-5 gap-1 border-x-0 border-b-0 border-t border-white/40 bg-card/85 px-2 pb-[max(0.45rem,env(safe-area-inset-bottom))] pt-1.5 shadow-[0_-12px_36px_-24px_hsl(var(--glass-shadow)/0.55)] backdrop-blur-2xl sm:hidden">
        {links.map((link) => {
          const Icon = link.icon;
          return (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex min-w-0 flex-col items-center justify-center gap-1 rounded-[0.9rem] px-1 py-2 text-[0.65rem] font-medium leading-none transition sm:flex-row sm:gap-1.5 sm:rounded-full sm:px-3 sm:py-1.5 sm:text-sm",
                  (isActive || (link.to === "/profile" && managementRoute))
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                  link.to === "/chat" && !hasAccounts && "opacity-60"
                )
              }
              title={link.to === "/chat" && !hasAccounts ? t("agent.noAccountsTitle") : undefined}
            >
              <Icon className="h-[1.15rem] w-[1.15rem] shrink-0" aria-hidden />
              <span className="max-w-full truncate">{t(link.labelKey)}</span>
            </NavLink>
          );
        })}
      </nav>
      <main
        className={cn(
          chatActive
            ? "min-h-0 flex-1 overflow-hidden pb-[calc(4.75rem+env(safe-area-inset-bottom))] sm:pb-0"
            : "pb-28 sm:pb-12"
        )}
      >
        <Outlet context={{ assistant, setChatPresence, demoMode, setDemoMode } satisfies LayoutOutletContext} />
      </main>
    </div>
  );
}
