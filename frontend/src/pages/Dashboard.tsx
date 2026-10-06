import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Rectangle,
  ResponsiveContainer,
  Sankey,
  Pie,
  PieChart,
  type PieLabelRenderProps,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowUpRight,
  BriefcaseBusiness,
  ChartLine,
  ChartPie,
  Landmark,
  Loader2,
  SlidersHorizontal,
  WalletCards,
  Workflow,
} from "lucide-react";
import { useNavigate, useOutletContext } from "react-router-dom";

import {
  api,
  type Account,
  type AssetsOverview,
  type Connection,
  type FlowResponse,
  type StatsSummary,
  type TimeseriesResponse,
} from "@/api/client";
import { useAppSetup } from "@/auth/AppSetupContext";
import { Card, Input } from "@/components/ui";
import type { LayoutOutletContext } from "@/components/Layout";
import { categoryColor, categorySlugForLabel, seriesColor, themeHsl } from "@/lib/colors";
import { AccountIcon, categoryIconForSlug } from "@/lib/icons";
import { THEME_CHANGE_EVENT } from "@/lib/theme";
import { formatMoney, periodRange, shiftPeriod } from "@/lib/utils";

type Grain = "week" | "month" | "year";
type GroupBy = "category" | "account";
type DistributionMode = "income" | "expense";
type AccountPresentation = {
  source: string;
  provider?: string;
  accountType?: string;
};
type CategoryPresentation = {
  slug: string | null;
  color: string | null;
  colorKey: string | null;
  icon: string | null;
};
type DistributionEntry = {
  key: string;
  name: string;
  value: number;
  index: number;
};
type DistributionLabelLayout = {
  side: "left" | "right";
  y: number;
  angle: number;
};
type ChartTooltipEntry = {
  name?: string | number;
  value?: string | number;
  color?: string;
  fill?: string;
  payload?: unknown;
};

type FlowTooltipNode = {
  name?: string;
  role?: FlowResponse["nodes"][number]["role"];
  category_slug?: string | null;
  color?: string | null;
  color_key?: string | null;
  icon?: string | null;
  group_by?: string | null;
  group_key?: string | null;
  account_source?: string | null;
  account_provider?: string | null;
  payload?: FlowTooltipNode;
};

type FlowNodeSelection = Pick<FlowResponse["nodes"][number], "name" | "role" | "category_slug" | "color" | "color_key" | "icon" | "group_by" | "group_key" | "account_source" | "account_provider">;

// Use the same identity for a flow node everywhere (Sankey shapes and the
// summary list).  The displayed label can contain role prefixes such as
// "In ·" or "Out ·", so comparing labels alone makes a second click fail to
// toggle when Recharts supplies a slightly different representation.
function flowNodeKey(node: FlowNodeSelection) {
  const identity = node.group_key || node.category_slug || node.name;
  return [node.role, node.group_by || "", identity]
    .map((part) => String(part || "").trim().toLocaleLowerCase())
    .join(":");
}

function flowTooltipNode(entry?: ChartTooltipEntry): FlowTooltipNode | null {
  const sankeyItem = entry?.payload as { payload?: FlowTooltipNode & {
    source?: FlowTooltipNode;
    target?: FlowTooltipNode;
  } } | undefined;
  const payload = sankeyItem?.payload;
  if (!payload) return null;

  const candidates = [payload, payload.source?.payload || payload.source, payload.target?.payload || payload.target];
  return candidates.find((node) => Boolean(node?.category_slug || node?.group_key)) || null;
}

function cleanFlowLabel(value: string) {
  const tail = value.split(" - ").at(-1) || value;
  return tail.replace(/^(In|Out|Save) · /, "");
}

function segmentIcon(key: string) {
  const label = key.replace(/^[ei]:/, "");
  return categoryIconForSlug(categorySlugForLabel(label) || "other");
}

function ChartTooltip({
  active,
  payload,
  label,
  language,
  mode,
  incomeOrder,
  expenseOrder,
  groupBy,
  accountMetaByName,
  onOpenTransactions,
}: {
  active?: boolean;
  payload?: ChartTooltipEntry[];
  label?: string | number;
  language: string;
  mode: "flow" | "trend";
  incomeOrder?: string[];
  expenseOrder?: string[];
  groupBy?: GroupBy;
  accountMetaByName?: Map<string, AccountPresentation>;
  onOpenTransactions?: (node: {
    categorySlug?: string;
    account?: string;
    role: FlowResponse["nodes"][number]["role"];
  }) => void;
}) {
  const { t } = useTranslation();
  if (!active || !payload?.length) return null;

  const entries = payload
    .map((entry) => ({ ...entry, numericValue: Number(entry.value || 0) }))
    .filter((entry) => Number.isFinite(entry.numericValue) && entry.numericValue > 0)
    .sort((a, b) => b.numericValue - a.numericValue);
  if (entries.length === 0) return null;

  const visible = mode === "flow" ? entries.slice(0, 2) : entries;
  const remaining = entries.length - visible.length;
  const sortByOrder = (items: typeof entries, order: string[]) => {
    const ranks = new Map(order.map((key, index) => [key, index]));
    return [...items].sort((a, b) => {
      const aRank = ranks.get(String(a.name)) ?? Number.MAX_SAFE_INTEGER;
      const bRank = ranks.get(String(b.name)) ?? Number.MAX_SAFE_INTEGER;
      return bRank - aRank;
    });
  };
  const trendIncome = mode === "trend"
    ? sortByOrder(entries.filter((entry) => String(entry.name || "").startsWith("i:")), incomeOrder || [])
    : [];
  const trendExpenses = mode === "trend"
    ? sortByOrder(entries.filter((entry) => String(entry.name || "").startsWith("e:")), expenseOrder || [])
    : [];
  const flowName = String(visible[0]?.name || "");
  const selectedFlowNode = mode === "flow" ? flowTooltipNode(visible[0]) : null;
  const selectedFlowSlug = selectedFlowNode?.category_slug || null;
  const selectedFlowAccount = selectedFlowNode?.group_by === "account"
    ? selectedFlowNode.group_key || null
    : null;
  const flowRole = selectedFlowNode?.role
    || (flowName.includes("In ·") ? "income" : flowName.includes("Save ·") ? "saving" : flowName.includes("Out ·") ? "expense" : null);
  const selectedFlowColor = selectedFlowSlug
    ? categoryColor(
        selectedFlowSlug,
        selectedFlowNode?.color_key || undefined,
        selectedFlowNode?.color || undefined,
      )
    : flowRole === "income"
      ? themeHsl("accent")
      : flowRole === "saving"
        ? themeHsl("flow-saving")
        : flowRole === "expense"
          ? themeHsl("danger")
        : themeHsl("flow-balance");
  const flowKindColor = flowRole === "income"
    ? themeHsl("accent")
    : flowRole === "expense"
      ? themeHsl("danger")
      : flowRole === "saving"
        ? themeHsl("flow-saving")
        : themeHsl("flow-balance");
  const SelectedFlowIcon = selectedFlowNode
    ? categoryIconForSlug(selectedFlowNode.icon || selectedFlowSlug || "other")
    : null;
  const flowKind = selectedFlowNode?.role === "saving" || flowName.includes("Save ·")
    ? t("dashboard.savings")
    : selectedFlowNode?.role === "expense" || flowName.includes("Out ·")
      ? t("dashboard.expenses")
      : selectedFlowNode?.role === "income" || flowName.includes("In ·")
        ? t("dashboard.income")
        : t("dashboard.flow");
  const flowLabel = selectedFlowNode?.name
    ? cleanFlowLabel(selectedFlowNode.name)
    : cleanFlowLabel(flowName);

  return (
    <div className="max-h-[min(22rem,calc(100vh-3rem))] min-w-[11rem] max-w-[min(20rem,calc(100vw-2rem))] overflow-y-auto rounded-[1.35rem] border border-white/45 bg-card/95 p-3 text-card-foreground shadow-[0_18px_45px_-24px_hsl(var(--glass-shadow)/0.75)] backdrop-blur-2xl">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {mode === "flow" && SelectedFlowIcon && selectedFlowColor && (
            <span
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg shadow-sm ring-1 ring-white/40"
              style={{
                backgroundColor: selectedFlowColor,
                color: themeHsl("category-label-foreground"),
              }}
            >
              {selectedFlowNode?.account_source ? (
                <AccountIcon
                  source={selectedFlowNode.account_source}
                  provider={selectedFlowNode.account_provider || undefined}
                  className="h-3.5 w-3.5"
                />
              ) : (
                <SelectedFlowIcon className="h-3.5 w-3.5" strokeWidth={2.25} aria-hidden />
              )}
            </span>
          )}
          <p className="truncate text-xs font-semibold text-foreground">
            {mode === "flow" ? flowLabel : label}
          </p>
        </div>
        {mode === "flow" && (
          <span className="shrink-0 rounded-full bg-muted/65 px-2 py-0.5 text-[0.65rem] font-medium text-muted-foreground">
            {flowKind}
          </span>
        )}
      </div>
      {mode === "trend" ? (
        <div className="grid grid-cols-2 gap-3">
          {[
            { label: t("dashboard.income"), entries: trendIncome, color: themeHsl("accent"), order: incomeOrder || [] },
            { label: t("dashboard.expenses"), entries: trendExpenses, color: themeHsl("danger"), order: expenseOrder || [] },
          ].map((group) => (
            <div key={group.label} className="min-w-0">
              <div className="flex items-center gap-1.5 text-[0.68rem] font-semibold text-foreground">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: group.color }} />
                <span className="truncate">{group.label}</span>
              </div>
              <div className="mt-2 max-h-40 space-y-1.5 overflow-y-auto">
                {group.entries.length === 0 ? (
                  <span className="text-[0.68rem] text-muted-foreground">—</span>
                ) : group.entries.map((entry, index) => {
                  const rawName = String(entry.name || "");
                  const entryLabel = rawName.replace(/^[ei]:/, "");
                  const colorIndex = group.order.indexOf(rawName);
                  const SegmentIcon = segmentIcon(rawName);
                  const accountMeta = groupBy === "account"
                    ? accountMetaByName?.get(entryLabel.trim().toLocaleLowerCase())
                    : undefined;
                  const segmentColor = seriesColor(rawName, colorIndex >= 0 ? colorIndex : index);
                  return (
                    <div key={`${rawName}-${index}`} className="flex items-center gap-1.5 text-xs">
                      <span
                        className="grid h-4 w-4 shrink-0 place-items-center rounded-md"
                        style={{ background: segmentColor, color: themeHsl("category-label-foreground") }}
                      >
                        {accountMeta ? (
                          <AccountIcon
                            source={accountMeta.source}
                            provider={accountMeta.provider}
                            accountType={accountMeta.accountType}
                            className="h-3 w-3"
                          />
                        ) : (
                          <SegmentIcon className="h-3 w-3" strokeWidth={2.25} aria-hidden />
                        )}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-muted-foreground" title={rawName.slice(2)}>
                        {rawName.replace(/^[ei]:/, "")}
                      </span>
                      <span className="shrink-0 font-semibold tabular-nums text-foreground">
                        {formatMoney(entry.numericValue, "EUR", language)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-1.5">
          {visible.map((entry, index) => {
            const rawName = String(entry.name || "");
            const entryLabel = cleanFlowLabel(rawName);
            return (
              <div key={`${rawName}-${index}`} className="flex items-center gap-2 text-xs">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full ring-2 ring-white/35"
                  style={{
                    background: index === 0
                      ? flowKindColor
                      : selectedFlowColor || entry.color || entry.fill || themeHsl("flow-balance"),
                  }}
                />
                <span className="min-w-0 flex-1 truncate text-muted-foreground">
                  {index === 0 ? flowKind : entryLabel}
                </span>
                <span
                  className="shrink-0 font-semibold tabular-nums"
                  style={{ color: index === 0 ? flowKindColor : undefined }}
                >
                  {formatMoney(entry.numericValue, "EUR", language)}
                </span>
              </div>
            );
          })}
        </div>
      )}
      {remaining > 0 && (
        <p className="mt-2 text-[0.65rem] text-muted-foreground">
          {t("dashboard.moreCategories", { count: remaining })}
        </p>
      )}
      {mode === "flow" && (selectedFlowSlug || selectedFlowAccount) && (
        <button
          type="button"
          className="mt-2.5 inline-flex w-full items-center justify-between rounded-lg border border-border/40 bg-background/20 px-2 py-1.5 text-left text-[0.68rem] font-semibold text-muted-foreground transition hover:border-border/65 hover:bg-muted/45 hover:text-foreground"
          onClick={() => onOpenTransactions?.({
            categorySlug: selectedFlowSlug || undefined,
            account: selectedFlowAccount || undefined,
            role: selectedFlowNode?.role || "expense",
          })}
        >
          <span>{t("dashboard.openTransactions")}</span>
          <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
    </div>
  );
}

function compactAxisValue(value: number, language: string) {
  const absolute = Math.abs(value);
  const units = [
    { threshold: 1_000_000_000, suffix: "B" },
    { threshold: 1_000_000, suffix: "M" },
    { threshold: 1_000, suffix: "K" },
  ];
  const unit = units.find(({ threshold }) => absolute >= threshold);
  if (!unit) return new Intl.NumberFormat(language, { maximumFractionDigits: 0 }).format(value);

  return `${new Intl.NumberFormat(language, { maximumFractionDigits: 1 }).format(
    value / unit.threshold
  )}${unit.suffix}`;
}

function localDateValue(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isoWeek(date: Date) {
  const value = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const day = value.getUTCDay() || 7;
  value.setUTCDate(value.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(value.getUTCFullYear(), 0, 1));
  return Math.ceil(((value.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7);
}

function flowNodeShape(
  props: unknown,
  sankeyLinks: Array<{ value?: number }> = [],
  onSelectNode?: (node: FlowNodeSelection) => void,
  selectedNodeName?: string | null,
  onHoverNode?: (node: FlowNodeSelection | null) => void,
) {
  const node = props as Record<string, unknown>;
  const payload = (node.payload || {}) as {
    name?: string;
    role?: FlowResponse["nodes"][number]["role"];
    category_slug?: string | null;
    color?: string | null;
    color_key?: string | null;
    icon?: string | null;
    group_by?: string | null;
    group_key?: string | null;
    account_source?: string | null;
    account_provider?: string | null;
    sourceLinks?: Array<number | { value?: number }>;
    targetLinks?: Array<number | { value?: number }>;
  };
  const name = payload.name || String(node.name || "");
  const role = payload.role || "hub";
  const categorySlug = payload.category_slug || null;
  const categoryColorKey = payload.color_key || null;
  const categoryFallbackColor = payload.color || null;
  const categoryIcon = payload.icon || null;
  const groupKey = payload.group_key || null;
  const accountSource = payload.account_source || null;
  const accountProvider = payload.account_provider || null;
  const x = Number(node.x || 0);
  const y = Number(node.y || 0);
  const width = Math.max(10, Number(node.width || 0));
  const height = Math.max(0.75, Number(node.height || 0));
  const isIncome = role === "income";
  const isSaving = role === "saving";
  const isExpense = role === "expense";
  // Recharts exposes sourceLinks/targetLinks on the payload as link indexes,
  // not as the link objects themselves. Resolve those indexes against the
  // chart data so the hub can identify the shorter side of an imbalanced flow.
  const incomingLinks = (node.sourceLinks || payload.sourceLinks || []) as Array<number | { value?: number }>;
  const outgoingLinks = (node.targetLinks || payload.targetLinks || []) as Array<number | { value?: number }>;
  const linkTotal = (links: Array<number | { value?: number }>) => links.reduce<number>((sum, link) => {
    const value = typeof link === "number" ? sankeyLinks[link]?.value : link.value;
    return sum + Number(value || 0);
  }, 0);
  const outgoingTotal = linkTotal(outgoingLinks);
  const incomingTotal = linkTotal(incomingLinks);
  const fill = isIncome
    ? themeHsl("accent")
    : isSaving
      ? themeHsl("flow-saving")
    : isExpense
      ? themeHsl("danger")
      : themeHsl("flow-balance");
  const label = name.replace(/^(In|Out|Save) · /, "");
  const displayLabel = label.length > 14 ? `${label.slice(0, 13)}…` : label;
  const labelOnLeft = isExpense || isSaving;
  const isEndpoint = ["income", "expense", "saving"].includes(role || "");
  const markerX = labelOnLeft ? x - 10 : x + width + 10;
  const markerY = y + height / 2;
  const textX = labelOnLeft ? markerX - 9 : markerX + 9;
  const CategoryGlyph = categoryIconForSlug(categoryIcon || categorySlug || "other");
  const radius = Math.min(width / 2, height / 2, 4);
  const isHub = role === "hub";
  // Endpoint nodes get a fully rounded outer side. For the middle hub, only
  // the lower corner of the shorter side is rounded: links are laid out from
  // the top, so the imbalance appears as a hard step at the bottom.
  const roundLeftTop = isIncome;
  const roundLeftBottom = isIncome || (isHub && outgoingTotal > incomingTotal + 0.01);
  const roundRightTop = isExpense || isSaving;
  const roundRightBottom = isExpense || isSaving || (isHub && incomingTotal > outgoingTotal + 0.01);
  const nodePath = [
    `M ${x + (roundLeftTop ? radius : 0)} ${y}`,
    `L ${x + width - (roundRightTop ? radius : 0)} ${y}`,
    ...(roundRightTop
      ? [`Q ${x + width} ${y} ${x + width} ${y + radius}`]
      : []),
    `L ${x + width} ${y + height - (roundRightBottom ? radius : 0)}`,
    ...(roundRightBottom
      ? [`Q ${x + width} ${y + height} ${x + width - radius} ${y + height}`]
      : []),
    `L ${x + (roundLeftBottom ? radius : 0)} ${y + height}`,
    ...(roundLeftBottom
      ? [`Q ${x} ${y + height} ${x} ${y + height - radius}`]
      : []),
    `L ${x} ${y + (roundLeftTop ? radius : 0)}`,
    ...(roundLeftTop ? [`Q ${x} ${y} ${x + radius} ${y}`] : []),
    "Z",
  ].join(" ");

  const selectable = isEndpoint && Boolean(categorySlug || groupKey);
  const selection = {
    name,
    role,
    category_slug: categorySlug,
    color: categoryFallbackColor,
    color_key: categoryColorKey,
    icon: categoryIcon,
    group_by: payload.group_by || null,
    group_key: groupKey,
    account_source: accountSource,
    account_provider: accountProvider,
  } satisfies FlowNodeSelection;
  const isDimmed = Boolean(selectedNodeName && selectable && selectedNodeName !== flowNodeKey(selection));
  const selectNode = (event?: MouseEvent) => {
    event?.stopPropagation();
    if (selectable) onSelectNode?.(selection);
  };

  return (
    <g
      style={selectable ? { cursor: "pointer" } : undefined}
      data-flow-interactive={selectable ? "true" : undefined}
      onPointerDown={selectable ? (event) => {
        event.stopPropagation();
        selectNode();
      } : undefined}
      onClick={selectable ? (event) => event.stopPropagation() : undefined}
      onMouseEnter={selectable ? () => onHoverNode?.(selection) : undefined}
      onMouseLeave={selectable ? () => onHoverNode?.(null) : undefined}
      onKeyDown={selectable ? (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectNode();
        }
      } : undefined}
      role={selectable ? "button" : undefined}
      tabIndex={selectable ? 0 : undefined}
      opacity={isDimmed ? 0.22 : 1}
    >
      <path
        d={nodePath}
        fill={fill}
      />
      {isEndpoint && (
        <g>
          <title>{label}</title>
          <circle
            cx={markerX}
            cy={markerY}
            r={7.25}
            fill={themeHsl("card")}
            fillOpacity={0.92}
            stroke={fill}
            strokeWidth={1.25}
          />
          {accountSource ? (
            <foreignObject x={markerX - 5} y={markerY - 5} width={10} height={10}>
              <div className="grid h-2.5 w-2.5 place-items-center">
                <AccountIcon
                  source={accountSource}
                  provider={accountProvider || undefined}
                  className="h-2.5 w-2.5"
                />
              </div>
            </foreignObject>
          ) : (
            <CategoryGlyph
              x={markerX - 4.5}
              y={markerY - 4.5}
              width={9}
              height={9}
              color={fill}
              strokeWidth={2.25}
            />
          )}
          <text
            x={textX}
            y={markerY}
            dy="0.35em"
            textAnchor={labelOnLeft ? "end" : "start"}
            fill={themeHsl("foreground")}
            stroke={themeHsl("card")}
            strokeWidth={3}
            strokeOpacity={0.9}
            strokeLinejoin="round"
            paintOrder="stroke"
            fontSize={9.5}
            fontWeight={600}
          >
            {displayLabel}
          </text>
        </g>
      )}
    </g>
  );
}

function flowNodeFromUnknown(value: unknown): FlowNodeSelection | null {
  let candidate = value;
  for (let index = 0; index < 3; index += 1) {
    if (!candidate || typeof candidate !== "object") break;
    const record = candidate as Record<string, unknown>;
    if (typeof record.name === "string") {
      const role = record.role;
      return {
        name: record.name,
        role: role === "income" || role === "expense" || role === "saving" || role === "hub" ? role : "hub",
        category_slug: typeof record.category_slug === "string" ? record.category_slug : null,
        group_by: typeof record.group_by === "string" ? record.group_by : null,
        group_key: typeof record.group_key === "string" ? record.group_key : null,
        account_source: typeof record.account_source === "string" ? record.account_source : null,
        account_provider: typeof record.account_provider === "string" ? record.account_provider : null,
      };
    }
    candidate = record.payload;
  }
  return null;
}

function flowLinkShape(
  props: unknown,
  onSelectNode?: (node: FlowNodeSelection) => void,
  selectedNodeName?: string | null,
  onHoverNode?: (node: FlowNodeSelection | null) => void,
) {
  const link = props as Record<string, unknown>;
  const sourceX = Number(link.sourceX || 0);
  const targetX = Number(link.targetX || 0);
  const sourceY = Number(link.sourceY || 0);
  const targetY = Number(link.targetY || 0);
  const linkWidth = Math.max(0.75, Number(link.linkWidth || link.width || 1));
  const halfWidth = linkWidth / 2;
  const gap = Math.max(0, targetX - sourceX);
  const straight = Math.min(20, gap * 0.16);
  const curveStartX = sourceX + straight;
  const curveEndX = targetX - straight;
  const curveWidth = Math.max(0, curveEndX - curveStartX);
  const sourceControlX = curveStartX + curveWidth * 0.42;
  const targetControlX = curveEndX - curveWidth * 0.42;
  const payload = (link.payload || {}) as Record<string, unknown>;
  const sourceNode = flowNodeFromUnknown(link.source) || flowNodeFromUnknown(payload.source);
  const targetNode = flowNodeFromUnknown(link.target) || flowNodeFromUnknown(payload.target);
  const endpointNode = sourceNode?.role === "hub"
    ? targetNode
    : targetNode?.role === "hub"
      ? sourceNode
      : null;
  const targetRole = targetNode?.role;
  const flowRole = endpointNode?.role || targetRole;
  const isSaving = endpointNode?.role === "saving";
  const selectable = Boolean(endpointNode && endpointNode.role !== "hub" && (endpointNode.category_slug || endpointNode.group_key));
  const endpointKey = endpointNode ? flowNodeKey(endpointNode) : null;
  const isDimmed = Boolean(selectedNodeName && selectable && endpointKey !== selectedNodeName);
  const d = [
    `M ${sourceX} ${sourceY - halfWidth}`,
    `L ${curveStartX} ${sourceY - halfWidth}`,
    `C ${sourceControlX} ${sourceY - halfWidth}, ${targetControlX} ${targetY - halfWidth}, ${curveEndX} ${targetY - halfWidth}`,
    `L ${targetX} ${targetY - halfWidth}`,
    `L ${targetX} ${targetY + halfWidth}`,
    `L ${curveEndX} ${targetY + halfWidth}`,
    `C ${targetControlX} ${targetY + halfWidth}, ${sourceControlX} ${sourceY + halfWidth}, ${curveStartX} ${sourceY + halfWidth}`,
    `L ${sourceX} ${sourceY + halfWidth}`,
    "Z",
  ].join(" ");

  const hoverNode = endpointNode && selectable ? endpointNode : null;

  return (
    <path
      d={d}
      data-flow-interactive={selectable ? "true" : undefined}
      fill={themeHsl(
        isSaving
          ? "flow-saving-link"
          : flowRole === "expense"
            ? "danger"
            : flowRole === "income"
              ? "accent"
              : "chart-link"
      )}
      fillOpacity={isDimmed ? 0.07 : isSaving ? 0.58 : flowRole ? 0.34 : 0.42}
      style={selectable ? { cursor: "pointer" } : undefined}
      onPointerDown={selectable ? (event) => {
        event.stopPropagation();
        onSelectNode?.(endpointNode as FlowNodeSelection);
      } : undefined}
      onClick={selectable ? (event) => event.stopPropagation() : undefined}
      onMouseEnter={hoverNode ? () => onHoverNode?.(hoverNode) : undefined}
      onMouseLeave={hoverNode ? () => onHoverNode?.(null) : undefined}
    />
  );
}

function stackShape(stackKeys: string[], currentKey: string, stackName: string) {
  return (props: unknown) => {
    const shapeProps = props as Record<string, unknown>;
    const payload = (shapeProps.payload || {}) as Record<string, string | number>;
    const x = Number(shapeProps.x);
    const y = Number(shapeProps.y);
    const width = Number(shapeProps.width);
    const height = Number(shapeProps.height);
    const value = Number(payload[currentKey] || 0);
    if (![x, y, width, height, value].every(Number.isFinite) || value <= 0 || height <= 0) {
      return <Rectangle {...shapeProps} radius={0} />;
    }

    const keyIndex = stackKeys.indexOf(currentKey);
    if (keyIndex < 0) return <Rectangle {...shapeProps} radius={0} />;
    const below = stackKeys
      .slice(0, keyIndex)
      .reduce((sum, key) => sum + Number(payload[key] || 0), 0);
    const total = stackKeys.reduce((sum, key) => sum + Number(payload[key] || 0), 0);
    const pixelsPerUnit = height / value;
    const stackBottom = y + height + below * pixelsPerUnit;
    const stackHeight = total * pixelsPerUnit;
    const stackTop = stackBottom - stackHeight;
    // The bevel belongs to the whole stack, not to the height of the current segment.
    // This keeps tiny top segments visually consistent instead of shrinking their corners.
    const radius = Math.min(6, width / 2, stackHeight);
    const period = String(payload.period || "bucket").replace(/[^a-zA-Z0-9_-]/g, "");
    const keyPart = currentKey.replace(/[^a-zA-Z0-9_-]/g, "");
    const clipId = `stack-${stackName}-${period}-${keyPart}`;
    const stackPath = [
      `M ${x} ${stackBottom}`,
      `L ${x} ${stackTop + radius}`,
      `Q ${x} ${stackTop} ${x + radius} ${stackTop}`,
      `L ${x + width - radius} ${stackTop}`,
      `Q ${x + width} ${stackTop} ${x + width} ${stackTop + radius}`,
      `L ${x + width} ${stackBottom}`,
      "Z",
    ].join(" ");
    return (
      <>
        <defs>
          <clipPath id={clipId}>
            <path d={stackPath} />
          </clipPath>
        </defs>
        <g clipPath={`url(#${clipId})`}>
          <Rectangle {...shapeProps} radius={0} />
        </g>
      </>
    );
  };
}

export function DashboardPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { hasAccounts, accountSetupInProgress } = useAppSetup();
  const { demoMode } = useOutletContext<LayoutOutletContext>();
  const todayValue = localDateValue(new Date());
  const currentMonthValue = todayValue.slice(0, 7);
  const currentYear = Number(todayValue.slice(0, 4));
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches
  );
  const [grain, setGrain] = useState<Grain>("year");
  const [anchor, setAnchor] = useState(() => new Date());
  const [groupBy, setGroupBy] = useState<GroupBy>("category");
  const [advanced, setAdvanced] = useState(false);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [stats, setStats] = useState<StatsSummary | null>(null);
  const [series, setSeries] = useState<TimeseriesResponse | null>(null);
  const [flow, setFlow] = useState<FlowResponse | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountsLoaded, setAccountsLoaded] = useState(false);
  const [accountsAvailable, setAccountsAvailable] = useState(false);
  const [assetsOverview, setAssetsOverview] = useState<AssetsOverview | null>(null);
  const [assetsLoaded, setAssetsLoaded] = useState(false);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [themeRevision, setThemeRevision] = useState(0);
  const [selectedPeriod, setSelectedPeriod] = useState<string | null>(null);
  const [selectedFlowKey, setSelectedFlowKey] = useState<string | null>(null);
  const [hoveredFlowKey, setHoveredFlowKey] = useState<string | null>(null);
  // When a selected flow is clicked a second time, keep the tooltip closed
  // until the pointer leaves that shape.  Otherwise the hover callback can
  // immediately reopen the popup after the click-to-toggle has cleared it.
  const [suppressedFlowHoverKey, setSuppressedFlowHoverKey] = useState<string | null>(null);
  const [selectedDistributionKey, setSelectedDistributionKey] = useState<string | null>(null);
  const [distributionMode, setDistributionMode] = useState<DistributionMode>("expense");
  const [desktopChartIndex, setDesktopChartIndex] = useState(0);
  const [mobileChartIndex, setMobileChartIndex] = useState(0);
  const mobileChartsRef = useRef<HTMLDivElement>(null);
  const mobileChartSectionsRef = useRef<Array<HTMLElement | null>>([]);
  const flowChartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const update = () => setIsMobile(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const refreshCharts = () => setThemeRevision((revision) => revision + 1);
    window.addEventListener(THEME_CHANGE_EVENT, refreshCharts);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, refreshCharts);
  }, []);

  useEffect(() => {
    if (!selectedFlowKey) return;
    const closeOnOutsideClick = (event: Event) => {
      const target = event.target;
      if (
        target instanceof Element &&
        (target.closest("[data-flow-tooltip]") || target.closest("[data-flow-selection]"))
      ) {
        return;
      }
      if (target instanceof Node && !flowChartRef.current?.contains(target)) {
        setSelectedFlowKey(null);
        setHoveredFlowKey(null);
        setSuppressedFlowHoverKey(null);
      }
    };
    document.addEventListener("click", closeOnOutsideClick);
    return () => document.removeEventListener("click", closeOnOutsideClick);
  }, [selectedFlowKey]);

  // Trend and distribution data use account names as their grouping keys. Load
  // the same account/connection metadata used by the Accounts page so those
  // keys can render the provider's logo instead of a generic category glyph.
  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([api.accounts(), api.connections()])
      .then(([accountResult, connectionResult]) => {
        if (cancelled) return;
        if (accountResult.status === "fulfilled") {
          setAccounts(accountResult.value);
          setAccountsAvailable(true);
        }
        if (connectionResult.status === "fulfilled") {
          setConnections(connectionResult.value);
        }
      })
      .finally(() => {
        if (!cancelled) setAccountsLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!hasAccounts) {
      setAssetsOverview({ portfolios: [] });
      setAssetsLoaded(true);
      return;
    }
    let cancelled = false;
    api.assets()
      .then((data) => {
        if (!cancelled) setAssetsOverview(data);
      })
      .catch(() => {
        // Keep the period analysis available even if an investment provider
        // is temporarily unavailable. The snapshot then clearly shows only
        // the values that could be loaded.
      })
      .finally(() => {
        if (!cancelled) setAssetsLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [hasAccounts]);

  const accountMetaByName = useMemo(() => {
    const providerByConnection = new Map(
      connections.map((connection) => [connection.id, connection.provider])
    );
    const metadata = new Map<string, AccountPresentation>();
    for (const account of accounts) {
      metadata.set(account.name.trim().toLocaleLowerCase(), {
        source: account.source,
        provider: account.connection_id == null
          ? undefined
          : providerByConnection.get(account.connection_id),
        accountType: account.account_type,
      });
    }
    // The flow response already carries the provider metadata for account
    // nodes. Use it as a fallback while the account list is still loading.
    for (const node of flow?.nodes ?? []) {
      if (node.group_by !== "account" || !node.account_source) continue;
      const label = cleanFlowLabel(node.name).trim().toLocaleLowerCase();
      if (!metadata.has(label)) {
        metadata.set(label, {
          source: node.account_source,
          provider: node.account_provider || undefined,
        });
      }
    }
    return metadata;
  }, [accounts, connections, flow]);

  const wealthSnapshot = useMemo(() => {
    const includedAccounts = accounts.filter((account) =>
      account.is_active
      && account.currency.toUpperCase() === "EUR"
      && account.current_balance !== null
      && Number.isFinite(Number(account.current_balance))
    );
    const includedPortfolios = (assetsOverview?.portfolios ?? []).filter((portfolio) =>
      portfolio.currency.toUpperCase() === "EUR"
      && Number.isFinite(Number(portfolio.total_market_value))
    );
    const liquid = includedAccounts.reduce(
      (sum, account) => sum + Math.max(0, Number(account.current_balance)),
      0,
    );
    const liabilities = includedAccounts.reduce(
      (sum, account) => sum + Math.max(0, -Number(account.current_balance)),
      0,
    );
    const invested = includedPortfolios.reduce(
      (sum, portfolio) => sum + Math.max(0, Number(portfolio.total_market_value)),
      0,
    );
    const timestamps = [
      ...includedAccounts.map((account) => account.balance_updated_at),
      ...includedPortfolios.map((portfolio) => portfolio.last_synced_at),
    ]
      .filter((value): value is string => Boolean(value))
      .map((value) => new Date(value).getTime())
      .filter(Number.isFinite);
    const currencies = new Set([
      ...accounts
        .filter((account) => account.is_active && account.current_balance !== null)
        .map((account) => account.currency.toUpperCase()),
      ...(assetsOverview?.portfolios ?? []).map((portfolio) => portfolio.currency.toUpperCase()),
    ]);
    currencies.delete("EUR");
    return {
      liquid,
      invested,
      liabilities,
      total: liquid + invested - liabilities,
      updatedAt: timestamps.length > 0 ? new Date(Math.max(...timestamps)) : null,
      excludedCurrencies: [...currencies].sort(),
    };
  }, [accounts, assetsOverview]);
  const wealthReady = accountsLoaded
    && assetsLoaded
    && accountsAvailable
    && assetsOverview !== null;
  const wealthUnavailable = accountsLoaded && assetsLoaded && !wealthReady;
  const wealthAssets = wealthSnapshot.liquid + wealthSnapshot.invested;
  const liquidShare = wealthAssets > 0
    ? Math.max(0, Math.min(100, (wealthSnapshot.liquid / wealthAssets) * 100))
    : 0;
  const investedShare = wealthAssets > 0
    ? Math.max(0, Math.min(100, (wealthSnapshot.invested / wealthAssets) * 100))
    : 0;
  const wealthUpdatedLabel = wealthSnapshot.updatedAt
    ? new Intl.DateTimeFormat(i18n.language, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(wealthSnapshot.updatedAt)
    : null;

  const range = useMemo(() => {
    if (customFrom && customTo) {
      const to = customTo > todayValue ? todayValue : customTo;
      const from = customFrom > to ? to : customFrom;
      return { from, to };
    }
    const selectedRange = periodRange(grain, anchor);
    return {
      from: selectedRange.from > todayValue ? todayValue : selectedRange.from,
      to: selectedRange.to > todayValue ? todayValue : selectedRange.to,
    };
  }, [customFrom, customTo, grain, anchor, todayValue]);

  const trendGrain: "day" | "week" | "month" | "year" =
    grain === "year" ? "month" : grain === "month" ? "week" : "day";

  const openTransactions = (options: {
    category?: string;
    account?: string;
    kind?: "income" | "expense";
    query?: string;
  } = {}) => {
    const params = new URLSearchParams({ from: range.from, to: range.to });
    if (options.category) params.set("category", options.category);
    if (options.account) params.set("account", options.account);
    if (options.kind) params.set("kind", options.kind);
    if (options.query) params.set("q", options.query);
    navigate(`/transactions?${params.toString()}`);
  };

  const handleMobileChartScroll = () => {
    const element = mobileChartsRef.current;
    if (!element || element.clientWidth <= 0) return;
    const sections = mobileChartSectionsRef.current;
    let nearestIndex = 0;
    let nearestDistance = Number.POSITIVE_INFINITY;
    sections.forEach((section, index) => {
      if (!section) return;
      const distance = Math.abs(element.scrollLeft - section.offsetLeft);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = index;
      }
    });
    setMobileChartIndex(nearestIndex);
  };

  const selectMobileChart = (index: number) => {
    setMobileChartIndex(index);
    const element = mobileChartsRef.current;
    const section = mobileChartSectionsRef.current[index];
    if (!element || !section) return;
    element.scrollTo({ left: section.offsetLeft, behavior: "smooth" });
  };

  useEffect(() => {
    if (!hasAccounts) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setSelectedDistributionKey(null);
    setSelectedFlowKey(null);
    setHoveredFlowKey(null);
    setSuppressedFlowHoverKey(null);
    const base = new URLSearchParams({ from: range.from, to: range.to });
    const ts = new URLSearchParams({
      from: range.from,
      to: range.to,
      grain: trendGrain,
      group_by: groupBy,
    });
    const requests: Promise<unknown>[] = [
      api.stats(base).then((data) => {
        if (!cancelled) setStats(data);
      }),
      api.statsTimeseries(ts).then((data) => {
        if (!cancelled) {
          setSeries(data);
          // Keep the latest available bucket selected so the trend always
          // opens with useful detail instead of an empty panel.
          setSelectedPeriod(data.buckets.at(-1)?.period ?? null);
        }
      }),
    ];
    requests.push(
      api.statsFlow(new URLSearchParams({
        from: range.from,
        to: range.to,
        group_by: groupBy,
      })).then((data) => {
        if (!cancelled) setFlow(data);
      })
    );

    Promise.all(requests)
      .then(() => {
        if (!cancelled) setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [hasAccounts, range.from, range.to, grain, groupBy, trendGrain]);

  const { chartData, expenseKeys, incomeKeys } = useMemo(() => {
    const buckets = series?.buckets ?? [];
    const eKeys = new Set<string>();
    const iKeys = new Set<string>();
    const rows = buckets.map((b) => {
      const row: Record<string, string | number> = { period: b.period };
      for (const s of b.expense_segments) {
        const k = `e:${s.key}`;
        eKeys.add(k);
        row[k] = Number(s.amount);
      }
      for (const s of b.income_segments) {
        const k = `i:${s.key}`;
        iKeys.add(k);
        row[k] = Number(s.amount);
      }
      return row;
    });
    const totalFor = (key: string) => rows.reduce((sum, row) => sum + Number(row[key] || 0), 0);
    // Recharts stacks the first series at the bottom. Descending totals
    // therefore keep the largest segment at the base and the smallest at the
    // top, with the same order in every period and in the detail card.
    const sortKeys = (keys: Set<string>) => [...keys].sort((a, b) => {
      const difference = totalFor(b) - totalFor(a);
      return difference || a.localeCompare(b, i18n.language);
    });
    const expenseKeys = sortKeys(eKeys);
    const incomeKeys = sortKeys(iKeys);
    return { chartData: rows, expenseKeys, incomeKeys };
  }, [i18n.language, series]);

  const categoryMetaBySeriesKey = useMemo(() => {
    const metadata = new Map<string, CategoryPresentation>();
    for (const bucket of series?.buckets ?? []) {
      for (const [prefix, segments] of [
        ["i", bucket.income_segments],
        ["e", bucket.expense_segments],
      ] as const) {
        for (const segment of segments) {
          metadata.set(`${prefix}:${segment.key}`, {
            slug: segment.category_slug,
            color: segment.color,
            colorKey: segment.color_key,
            icon: segment.icon,
          });
        }
      }
    }
    return metadata;
  }, [series]);

  const chartSeriesColor = (key: string, index: number) => {
    const metadata = categoryMetaBySeriesKey.get(key);
    return metadata?.slug
      ? categoryColor(
          metadata.slug,
          metadata.colorKey || undefined,
          metadata.color || undefined,
        )
      : seriesColor(key, index);
  };

  const chartSegmentIcon = (key: string) => {
    const metadata = categoryMetaBySeriesKey.get(key);
    return categoryIconForSlug(
      metadata?.icon || metadata?.slug || categorySlugForLabel(key.slice(2)) || "other"
    );
  };

  const selectedTrendRow = selectedPeriod
    ? chartData.find((row) => row.period === selectedPeriod) || null
    : null;
  const sortForSelectedPeriod = (keys: string[]) => {
    if (!selectedTrendRow) return keys;
    return [...keys].sort((a, b) => {
      const difference = Number(selectedTrendRow[b] || 0) - Number(selectedTrendRow[a] || 0);
      return difference || keys.indexOf(a) - keys.indexOf(b);
    });
  };
  const displayIncomeKeys = sortForSelectedPeriod(incomeKeys);
  const displayExpenseKeys = sortForSelectedPeriod(expenseKeys);
  const selectedIncomeSegments = selectedTrendRow
    ? displayIncomeKeys
      .map((key, index) => ({ key, index, amount: Number(selectedTrendRow[key] || 0) }))
      .filter((segment) => segment.amount > 0)
      .reverse()
    : [];
  const selectedExpenseSegments = selectedTrendRow
    ? displayExpenseKeys
      .map((key, index) => ({ key, index, amount: Number(selectedTrendRow[key] || 0) }))
      .filter((segment) => segment.amount > 0)
      .reverse()
    : [];

  const distributionDataByMode = useMemo(() => {
    const rows = selectedTrendRow ? [selectedTrendRow] : chartData;
    const build = (keys: string[]): DistributionEntry[] => keys
      .map((key, index) => ({
        key,
        name: key.slice(2),
        value: rows.reduce((sum, row) => sum + Number(row[key] || 0), 0),
        index,
      }))
      .filter((entry) => entry.value > 0);
    return {
      income: build(displayIncomeKeys),
      expense: build(displayExpenseKeys),
    };
  }, [chartData, displayExpenseKeys, displayIncomeKeys, selectedTrendRow]);

  const distributionLabelLayoutFor = (distributionData: DistributionEntry[]) => {
    if (distributionData.length === 0) return [] as DistributionLabelLayout[];

    const total = distributionData.reduce((sum, entry) => sum + entry.value, 0);
    const minAngle = 1.5;
    const paddingAngle = 1;
    const realTotalAngle = Math.max(0, 360 - distributionData.length * (minAngle + paddingAngle));
    let cursor = 0;
    const positions = distributionData.map((entry, index) => {
      if (index > 0) cursor += paddingAngle;
      const angle = minAngle + (total > 0 ? (entry.value / total) * realTotalAngle : 0);
      const midAngle = cursor + angle / 2;
      cursor += angle;
      const radians = (-midAngle * Math.PI) / 180;
      return {
        index,
        angle: midAngle,
        side: Math.cos(radians) >= 0 ? "right" as const : "left" as const,
        y: Math.sin(radians),
      };
    });

    // Keep labels on each side readable without changing the actual segment sizes.
    for (const side of ["left", "right"] as const) {
      const sidePositions = positions
        .filter((position) => position.side === side)
        .sort((a, b) => a.y - b.y);
      const minGap = 0.15;
      const minY = -0.82;
      const maxY = 0.82;
      sidePositions.forEach((position, index) => {
        position.y = index === 0 ? Math.max(minY, position.y) : Math.max(position.y, sidePositions[index - 1].y + minGap);
      });
      const overflow = (sidePositions.at(-1)?.y || 0) - maxY;
      if (overflow > 0) {
        sidePositions.forEach((position) => { position.y -= overflow; });
      }
      const underflow = minY - (sidePositions[0]?.y || 0);
      if (underflow > 0) {
        sidePositions.forEach((position) => { position.y += underflow; });
      }
    }

    return positions
      .sort((a, b) => a.index - b.index)
      .map(({ side, y, angle }) => ({ side, y, angle }));
  };

  const distributionLabelLayouts = useMemo(() => ({
    income: distributionLabelLayoutFor(distributionDataByMode.income),
    expense: distributionLabelLayoutFor(distributionDataByMode.expense),
  }), [distributionDataByMode]);

  const renderDistributionLabel = (
    distributionData: DistributionEntry[],
    distributionLabelLayout: DistributionLabelLayout[],
  ) => (props: PieLabelRenderProps) => {
    const index = Number(props.index ?? 0);
    const entry = distributionData[index];
    if (!entry) return null;

    const layout = distributionLabelLayout[index];
    const cx = Number(props.cx ?? 0);
    const cy = Number(props.cy ?? 0);
    const outerRadius = Number(props.outerRadius ?? 0);
    // Use Recharts' actual sector angle for the connector. The layout only
    // adjusts the text's vertical position to avoid collisions.
    const midAngle = Number(props.midAngle ?? layout?.angle ?? 0);
    const radians = (-midAngle * Math.PI) / 180;
    const actualSide = Math.cos(radians) >= 0 ? "right" : "left";
    const side = layout?.side === actualSide ? layout.side : actualSide;
    // Give the mobile ring a little breathing room: labels and their elbow
    // connectors sit outside the ring instead of visually terminating inside
    // its edge.
    const labelRadius = outerRadius * (isMobile ? 1.28 : 1.12);
    const labelY = cy + labelRadius * (layout?.side === actualSide ? layout.y : Math.sin(radians));
    const lineStartRadius = outerRadius * 0.985;
    const lineStartX = cx + lineStartRadius * Math.cos(radians);
    const lineStartY = cy + lineStartRadius * Math.sin(radians);
    const connectorRadius = outerRadius * (isMobile ? 1.14 : 1.02);
    const connectorX = cx + connectorRadius * Math.cos(radians);
    const connectorY = cy + connectorRadius * Math.sin(radians);
    const labelX = cx + labelRadius * (side === "right" ? 1 : -1);
    const textX = labelX + (side === "right" ? 4 : -4);
    const color = chartSeriesColor(entry.key, entry.index);
    const dimmed = selectedDistributionKey !== null && selectedDistributionKey !== entry.key;
    const maxLabelLength = isMobile ? 10 : 14;
    const label = entry.name.length > maxLabelLength
      ? `${entry.name.slice(0, maxLabelLength - 1)}…`
      : entry.name;

    return (
      <g pointerEvents="none" opacity={dimmed ? 0.32 : 0.92}>
        <path
          d={`M ${lineStartX} ${lineStartY} L ${connectorX} ${connectorY} L ${labelX} ${labelY}`}
          fill="none"
          stroke={color}
          strokeWidth={isMobile ? 1.5 : 1.35}
          strokeOpacity={isMobile ? 0.75 : 0.65}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx={labelX} cy={labelY} r={2.4} fill={color} />
        <text
          x={textX}
          y={labelY}
          dy="0.35em"
          textAnchor={side === "right" ? "start" : "end"}
          fill={themeHsl("foreground")}
          fontSize={isMobile ? 10.5 : 12}
          fontWeight={650}
        >
          {label}
        </text>
      </g>
    );
  };

  const sankeyData = useMemo(() => {
    if (!flow || flow.nodes.length === 0 || flow.links.length === 0) return null;
    return {
      nodes: flow.nodes.map((node) => ({ ...node })),
      links: flow.links.map((l) => ({
        source: l.source,
        target: l.target,
        value: l.value,
      })),
    };
  }, [flow]);

  const flowSummaryRows = useMemo(() => {
    if (!flow) return [] as Array<FlowNodeSelection & { amount: number }>;
    const totals = new Map<number, number>();
    for (const link of flow.links) {
      totals.set(link.source, (totals.get(link.source) || 0) + Number(link.value || 0));
      totals.set(link.target, (totals.get(link.target) || 0) + Number(link.value || 0));
    }
    const roleOrder: Record<FlowResponse["nodes"][number]["role"], number> = {
      income: 0,
      saving: 1,
      expense: 2,
      hub: 3,
    };
    return flow.nodes
      .map((node, index) => ({ ...node, amount: totals.get(index) || 0 }))
      .filter((node) => node.role !== "hub" && node.amount > 0)
      .sort((a, b) => roleOrder[a.role] - roleOrder[b.role] || b.amount - a.amount);
  }, [flow]);
  const selectedFlowRow = flowSummaryRows.find((row) => flowNodeKey(row) === selectedFlowKey) || null;
  const activeFlowKey = selectedFlowKey || (
    hoveredFlowKey && hoveredFlowKey !== suppressedFlowHoverKey ? hoveredFlowKey : null
  );
  const activeFlowRow = flowSummaryRows.find((row) => flowNodeKey(row) === activeFlowKey) || null;
  const activeFlowTooltipPayload = activeFlowRow
    ? [{
        name: activeFlowRow.name,
        value: activeFlowRow.amount,
        color: activeFlowRow.category_slug
          ? categoryColor(
              activeFlowRow.category_slug,
              activeFlowRow.color_key || undefined,
              activeFlowRow.color || undefined,
            )
          : undefined,
        payload: { payload: activeFlowRow },
      }]
    : undefined;
  const toggleFlowSelection = (node: FlowNodeSelection, source: "chart" | "summary" = "chart") => {
    const key = flowNodeKey(node);
    const shouldClear = selectedFlowKey === key;
    setSelectedFlowKey(shouldClear ? null : key);
    setHoveredFlowKey(shouldClear ? null : key);
    setSuppressedFlowHoverKey(shouldClear && source === "chart" ? key : null);
  };
  const handleFlowHover = (node: FlowNodeSelection | null) => {
    if (!node) {
      setHoveredFlowKey(null);
      setSuppressedFlowHoverKey(null);
      return;
    }
    const key = flowNodeKey(node);
    if (suppressedFlowHoverKey === key) return;
    setSuppressedFlowHoverKey(null);
    setHoveredFlowKey(key);
  };
  const openFlowRowTransactions = (row: FlowNodeSelection) => openTransactions(
    groupBy === "account"
      ? { account: cleanFlowLabel(row.name), kind: row.role === "income" ? "income" : "expense" }
      : { category: row.category_slug || undefined, kind: row.role === "income" ? "income" : "expense" }
  );

  const hasCustomRange = Boolean(customFrom && customTo);
  const nextPeriodStartsInFuture = periodRange(
    grain,
    shiftPeriod(grain, anchor, 1)
  ).from > todayValue;
  const periodLabel = hasCustomRange
    ? `${customFrom} → ${customTo}`
    : grain === "week"
      ? `${t("period.week")} ${isoWeek(anchor)} · ${new Intl.DateTimeFormat(i18n.language, {
          month: "short",
          year: "numeric",
        }).format(anchor)}`
      : grain === "month"
        ? new Intl.DateTimeFormat(i18n.language, { month: "long", year: "numeric" }).format(anchor)
        : String(anchor.getFullYear());
  const earliestYear = Math.min(anchor.getFullYear(), currentYear - 20);
  const yearChoices = Array.from(
    { length: currentYear - earliestYear + 1 },
    (_, index) => earliestYear + index
  );
  const chartViews = [
    { index: 0, label: t("dashboard.flow"), Icon: Workflow },
    { index: 1, label: t("dashboard.trend"), Icon: ChartLine },
    { index: 2, label: t("dashboard.distribution"), Icon: ChartPie },
  ];
  const distributionGroups: Array<{
    key: "income" | "expense";
    label: string;
    data: DistributionEntry[];
    layout: DistributionLabelLayout[];
  }> = [
    {
      key: "income",
      label: t("dashboard.income"),
      data: distributionDataByMode.income,
      layout: distributionLabelLayouts.income,
    },
    {
      key: "expense",
      label: t("dashboard.expenses"),
      data: distributionDataByMode.expense,
      layout: distributionLabelLayouts.expense,
    },
  ];

  if (!hasAccounts) {
    return (
      <div className="space-y-5">
        <h2 className="px-1 text-2xl font-semibold tracking-tight sm:text-3xl">
          {t("dashboard.title")}
        </h2>
        <Card className="px-6 py-12 text-center sm:py-16">
          {accountSetupInProgress ? (
            <>
              <Loader2 className="mx-auto h-8 w-8 animate-spin text-primary" aria-hidden />
              <h3 className="mt-4 text-lg font-semibold">{t("dashboard.accountSyncInProgressTitle")}</h3>
              <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
                {t("dashboard.accountSyncInProgressHint")}
              </p>
            </>
          ) : (
            <>
              <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-muted/55 text-muted-foreground">
                <Landmark className="h-6 w-6" aria-hidden />
              </span>
              <h3 className="mt-4 text-lg font-semibold">{t("dashboard.noAccountsTitle")}</h3>
              <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
                {t("dashboard.noAccountsHint")}
              </p>
              <button
                type="button"
                className="mt-5 inline-flex min-h-11 items-center justify-center rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition hover:-translate-y-px hover:shadow-md"
                onClick={() => navigate("/accounts")}
              >
                {t("dashboard.addAccount")}
              </button>
            </>
          )}
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2 px-1"><h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t("dashboard.title")}</h2>{demoMode && <span className="rounded-full bg-warning/15 px-2 py-1 text-[0.58rem] font-semibold uppercase tracking-[0.1em] text-warning">Demo</span>}</div>

      <Card className="overflow-hidden p-0">
        <div className="grid grid-cols-[minmax(0,1fr)_7rem] items-center gap-4 p-5 sm:grid-cols-[minmax(0,1fr)_9rem] sm:gap-6 sm:p-6 md:gap-8">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              <WalletCards className="h-4 w-4 text-primary" aria-hidden />
              {t("dashboard.currentPosition")}
            </div>
            <p className="mt-3 text-sm text-muted-foreground">{t("dashboard.netWorth")}</p>
            <p className="mt-1 truncate text-3xl font-semibold tracking-tight tabular-nums sm:text-4xl">
              {wealthReady ? formatMoney(wealthSnapshot.total, "EUR", i18n.language) : "—"}
            </p>
            {wealthUnavailable && (
              <p className="mt-2 max-w-xl text-xs leading-relaxed text-muted-foreground sm:text-sm">
                {t("dashboard.currentPositionUnavailable")}
              </p>
            )}
            {wealthReady && wealthUpdatedLabel && (
              <p className="mt-2 text-[0.68rem] text-muted-foreground/80">
                {t("dashboard.dataAsOf", { date: wealthUpdatedLabel })}
              </p>
            )}
          </div>

          <div className="flex items-center justify-end">
            <div
              className="relative grid h-28 w-28 shrink-0 place-items-center rounded-full p-[0.7rem] sm:h-36 sm:w-36 sm:p-[0.78rem]"
              style={{
                background: wealthAssets > 0
                  ? `conic-gradient(hsl(var(--accent)) 0 ${liquidShare}%, hsl(var(--primary)) ${liquidShare}% 100%)`
                  : "hsl(var(--muted))",
              }}
              role="img"
              aria-label={t("dashboard.wealthComposition")}
            >
              <div className="grid h-full w-full place-items-center rounded-full border border-white/35 bg-card/90 text-center">
                <div>
                  <p className="text-lg font-semibold tabular-nums sm:text-xl">
                    {wealthReady ? `${Math.round(investedShare)} %` : "—"}
                  </p>
                  <p className="text-[0.62rem] font-medium text-muted-foreground">
                    {t("dashboard.investedShare")}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className={`grid border-t border-border/35 ${wealthSnapshot.liabilities > 0 ? "sm:grid-cols-3" : "sm:grid-cols-2"}`}>
          <button
            type="button"
            className="group flex min-w-0 items-center gap-3 border-b border-border/30 px-5 py-4 text-left transition hover:bg-muted/20 sm:border-b-0 sm:border-r sm:px-6"
            onClick={() => navigate("/accounts")}
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-accent/12 text-accent">
              <Landmark className="h-4 w-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-xs text-muted-foreground">{t("dashboard.liquidFunds")}</span>
              <span className="mt-0.5 block truncate text-sm font-semibold tabular-nums sm:text-base">
                {wealthReady ? formatMoney(wealthSnapshot.liquid, "EUR", i18n.language) : "—"}
              </span>
            </span>
            <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/55 transition group-hover:text-foreground" aria-hidden />
          </button>
          <button
            type="button"
            className={`group flex min-w-0 items-center gap-3 px-5 py-4 text-left transition hover:bg-muted/20 sm:px-6 ${wealthSnapshot.liabilities > 0 ? "border-b border-border/30 sm:border-b-0 sm:border-r" : ""}`}
            onClick={() => navigate("/assets")}
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary/12 text-primary">
              <BriefcaseBusiness className="h-4 w-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-xs text-muted-foreground">{t("dashboard.investedFunds")}</span>
              <span className="mt-0.5 block truncate text-sm font-semibold tabular-nums sm:text-base">
                {wealthReady ? formatMoney(wealthSnapshot.invested, "EUR", i18n.language) : "—"}
              </span>
            </span>
            <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/55 transition group-hover:text-foreground" aria-hidden />
          </button>
          {wealthSnapshot.liabilities > 0 && (
            <button
              type="button"
              className="group flex min-w-0 items-center gap-3 px-5 py-4 text-left transition hover:bg-muted/20 sm:px-6"
              onClick={() => navigate("/accounts")}
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-danger/12 text-danger">
                <Landmark className="h-4 w-4" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-xs text-muted-foreground">{t("dashboard.liabilities")}</span>
                <span className="mt-0.5 block truncate text-sm font-semibold tabular-nums text-danger sm:text-base">
                  {wealthReady ? `−${formatMoney(wealthSnapshot.liabilities, "EUR", i18n.language)}` : "—"}
                </span>
              </span>
              <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/55 transition group-hover:text-foreground" aria-hidden />
            </button>
          )}
        </div>
        {wealthSnapshot.excludedCurrencies.length > 0 && (
          <p className="border-t border-border/25 px-5 py-2.5 text-[0.68rem] text-muted-foreground sm:px-6">
            {t("dashboard.excludedCurrencies", { currencies: wealthSnapshot.excludedCurrencies.join(", ") })}
          </p>
        )}
      </Card>

      <div className="px-1 pt-1">
        <h3 className="text-lg font-semibold tracking-tight">{t("dashboard.periodAnalysis")}</h3>
        <p className="mt-0.5 text-xs text-muted-foreground sm:text-sm">{t("dashboard.periodAnalysisHint")}</p>
      </div>

      <Card className="space-y-6 p-4 sm:p-6">
        <div className="dashboard-chart-controls rounded-2xl border border-border/25 bg-background/45 p-2.5 shadow-none backdrop-blur-md md:sticky md:top-4 md:z-20 md:backdrop-blur-xl sm:p-3">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="hidden text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground md:inline">
                {t("dashboard.periodLabel")}
              </span>
              <div className="inline-flex rounded-xl border border-border/55 bg-background/25 p-0.5">
                {(["week", "month", "year"] as Grain[]).map((g) => (
                  <button
                    key={g}
                    type="button"
                    title={t(`period.${g}`)}
                    aria-label={t(`period.${g}`)}
                    className={`h-8 w-9 rounded-[0.6rem] text-xs font-semibold transition ${
                      grain === g && !hasCustomRange
                        ? "bg-primary text-primary-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                    onClick={() => {
                      setGrain(g);
                      setAnchor((value) => (
                        periodRange(g, value).from > todayValue ? new Date() : value
                      ));
                      setCustomFrom("");
                      setCustomTo("");
                      setAdvanced(false);
                    }}
                  >
                    {t(`period.short.${g}`)}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid min-w-0 flex-1 grid-cols-[2rem_minmax(0,1fr)_2rem] items-center gap-1 md:max-w-[22rem]">
              <button
                type="button"
                className="h-9 rounded-xl text-xl text-muted-foreground transition hover:bg-muted/40 hover:text-foreground"
                onClick={() => {
                  setCustomFrom("");
                  setCustomTo("");
                  setAnchor((value) => shiftPeriod(grain, value, -1));
                }}
                aria-label={t("period.previous")}
              >
                ‹
              </button>
              <div className="dashboard-period-picker relative flex h-9 min-w-0 items-center justify-center overflow-hidden rounded-xl border border-border/55 bg-background/20 px-3 text-sm font-medium">
                <span className="truncate">{periodLabel}</span>
                {hasCustomRange ? null : grain === "year" ? (
                  <select
                    className="absolute inset-0 cursor-pointer opacity-0"
                    value={anchor.getFullYear()}
                    onChange={(event) => {
                      const selectedYear = Math.min(Number(event.target.value), currentYear);
                      setAnchor(new Date(selectedYear, 0, 1));
                    }}
                    aria-label={t("period.selectYear")}
                  >
                    {yearChoices.map((year) => <option key={year} value={year}>{year}</option>)}
                  </select>
                ) : (
                  <input
                    className="absolute inset-0 cursor-pointer opacity-0"
                    type={grain === "month" ? "month" : "date"}
                    max={grain === "month" ? currentMonthValue : todayValue}
                    value={grain === "month" ? localDateValue(anchor).slice(0, 7) : localDateValue(anchor)}
                    onChange={(event) => {
                      const parts = event.target.value.split("-").map(Number);
                      if (grain === "month" && parts.length >= 2) {
                        const selected = new Date(parts[0], parts[1] - 1, 1);
                        setAnchor(localDateValue(selected).slice(0, 7) > currentMonthValue ? new Date() : selected);
                      }
                      if (grain === "week" && parts.length >= 3) {
                        const selected = new Date(parts[0], parts[1] - 1, parts[2]);
                        setAnchor(localDateValue(selected) > todayValue ? new Date() : selected);
                      }
                    }}
                    aria-label={t("period.select")}
                  />
                )}
              </div>
              <button
                type="button"
                className="h-9 rounded-xl text-xl text-muted-foreground transition hover:bg-muted/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
                disabled={nextPeriodStartsInFuture}
                onClick={() => {
                  if (nextPeriodStartsInFuture) return;
                  setCustomFrom("");
                  setCustomTo("");
                  setAnchor((value) => shiftPeriod(grain, value, 1));
                }}
                aria-label={t("period.next")}
              >
                ›
              </button>
            </div>

            <div className="flex items-center justify-between gap-2 md:justify-end">
              <div
                className="inline-flex rounded-xl border border-border/55 bg-background/25 p-0.5"
                role="group"
                aria-label={`${t("dashboard.byCategory")} / ${t("dashboard.byAccount")}`}
              >
                {(["category", "account"] as GroupBy[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    className={`h-8 rounded-[0.6rem] px-2.5 text-[0.68rem] font-semibold transition ${
                      groupBy === mode
                        ? "bg-primary text-primary-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                    aria-pressed={groupBy === mode}
                    onClick={() => setGroupBy(mode)}
                  >
                    {t(mode === "category" ? "dashboard.byCategory" : "dashboard.byAccount")}
                  </button>
                ))}
              </div>
              <button
                type="button"
                className={`grid h-8 w-9 place-items-center rounded-xl transition hover:bg-muted/40 ${
                  advanced || hasCustomRange ? "bg-muted/50 text-foreground" : "text-muted-foreground"
                }`}
                title={t("dashboard.advanced")}
                aria-label={t("dashboard.advanced")}
                aria-expanded={advanced}
                onClick={() => setAdvanced((value) => !value)}
              >
                <SlidersHorizontal className="h-4 w-4" aria-hidden />
              </button>
            </div>
          </div>

          <div className="mt-3 hidden items-center justify-between gap-3 border-t border-border/35 pt-3 md:flex">
            <span className="text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              {t("dashboard.chartViews")}
            </span>
            <div className="flex min-w-0 items-center gap-1 rounded-xl border border-border/45 bg-background/25 p-0.5" role="tablist" aria-label={t("dashboard.chartViews")}>
              {chartViews.map((view) => (
                <button
                  key={view.index}
                  type="button"
                  role="tab"
                  aria-selected={desktopChartIndex === view.index}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                    desktopChartIndex === view.index
                      ? "bg-primary text-primary-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                  onClick={() => setDesktopChartIndex(view.index)}
                >
                  <view.Icon className="mr-1.5 inline-block h-3.5 w-3.5 align-[-0.15em]" aria-hidden />
                  {view.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 px-1 pt-2 sm:grid-cols-4 sm:px-2 sm:pt-3">
          {[
            {
              label: t("dashboard.income"),
              value: stats?.income ?? "0",
              color: themeHsl("accent"),
              align: "items-start text-left",
            },
            {
              label: t("dashboard.net"),
              value: stats?.net ?? "0",
              color: themeHsl("flow-balance"),
              align: "items-end text-right sm:items-center sm:text-center",
            },
            {
              label: t("dashboard.expenses"),
              value: stats?.spending ?? "0",
              color: themeHsl("danger"),
              align: "items-start text-left sm:items-center sm:text-center",
            },
            {
              label: t("dashboard.savings"),
              value: stats?.savings ?? "0",
              color: themeHsl("flow-saving"),
              align: "items-end text-right",
            },
          ].map((item) => (
            <div key={item.label} className={`flex min-w-0 flex-col ${item.align}`}>
              <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground sm:text-xs">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: item.color }} />
                {item.label}
              </span>
              <span className="mt-1 max-w-full truncate text-sm font-semibold tabular-nums sm:text-base">
                {formatMoney(item.value, "EUR", i18n.language)}
              </span>
            </div>
          ))}
        </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      <div
        ref={mobileChartsRef}
        className="chart-carousel flex w-full items-start snap-x snap-mandatory overflow-x-auto overscroll-x-contain md:block md:overflow-visible"
        onScroll={handleMobileChartScroll}
      >
      <section ref={(element) => { mobileChartSectionsRef.current[0] = element; }} className={`w-full shrink-0 snap-start pr-3 pt-2 md:w-auto md:shrink md:pr-0 ${desktopChartIndex !== 0 ? "md:hidden" : ""}`}>
        <div className="mb-4">
          <h3 className="inline-flex items-center gap-2 text-xl font-semibold"><Workflow className="h-5 w-5 text-muted-foreground" aria-hidden />{t("dashboard.flow")}</h3>
        </div>
        {!sankeyData ? (
          <p className="text-sm text-muted-foreground">{t("dashboard.flowEmpty")}</p>
        ) : (
          <div
            ref={flowChartRef}
            className="relative min-h-[22rem] w-full overflow-hidden rounded-2xl border border-border/35 bg-card/15 px-1 py-2 shadow-inner shadow-black/[0.025] sm:px-2 sm:py-3 md:min-h-[28rem]"
            style={{ height: Math.min(600, Math.max(360, sankeyData.nodes.length * 31)) }}
            onMouseLeave={() => handleFlowHover(null)}
            onClick={(event) => {
              const target = event.target;
              if (target instanceof Element && target.closest("[data-flow-tooltip]")) return;
              setSelectedFlowKey(null);
              handleFlowHover(null);
            }}
          >
            <ResponsiveContainer key={`flow-theme-${themeRevision}`} width="100%" height="100%">
              <Sankey
                data={sankeyData}
                node={(props) => flowNodeShape(
                  props,
                  sankeyData.links,
                  (node) => toggleFlowSelection(node, "chart"),
                  selectedFlowKey,
                  handleFlowHover,
                )}
                nodeWidth={8}
                nodePadding={20}
                sort={false}
                margin={isMobile
                  ? { left: 26, right: 26, top: 34, bottom: 22 }
                  : { left: 82, right: 82, top: 34, bottom: 22 }}
                link={(props) => flowLinkShape(
                  props,
                  (node) => toggleFlowSelection(node, "chart"),
                  selectedFlowKey,
                  handleFlowHover,
                )}
              >
              </Sankey>
            </ResponsiveContainer>
            {activeFlowRow && (
              <div
                data-flow-tooltip="true"
                className="pointer-events-auto absolute left-1/2 top-3 z-10 w-[min(20rem,calc(100%-1.5rem))] -translate-x-1/2"
                onMouseEnter={() => handleFlowHover(activeFlowRow)}
              >
                <ChartTooltip
                  active
                  payload={activeFlowTooltipPayload}
                  language={i18n.language}
                  mode="flow"
                  onOpenTransactions={({ categorySlug, account, role }) => openTransactions({
                    category: categorySlug,
                    account,
                    kind: role === "income" ? "income" : role === "expense" || role === "saving" ? "expense" : undefined,
                  })}
                />
              </div>
            )}
          </div>
        )}
        {flowSummaryRows.length > 0 ? (
          <div className="mt-3 min-h-[15rem] rounded-2xl border border-border/35 bg-background/25 p-3 sm:p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-foreground">{t("dashboard.flow")}</p>
                {selectedFlowRow && (
                  <p className="mt-0.5 text-xs text-muted-foreground">{cleanFlowLabel(selectedFlowRow.name)}</p>
                )}
              </div>
              {selectedFlowRow && (
                <span className="shrink-0 text-xs font-semibold tabular-nums text-foreground">
                  {formatMoney(selectedFlowRow.amount, "EUR", i18n.language)}
                </span>
              )}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {[
                { key: "income", label: t("dashboard.income"), roles: ["income"], color: themeHsl("accent") },
                { key: "outflow", label: `${t("dashboard.expenses")} · ${t("dashboard.savings")}`, roles: ["expense", "saving"], color: themeHsl("danger") },
              ].map((group) => {
                const rows = flowSummaryRows.filter((row) => group.roles.includes(row.role));
                return (
                  <div key={group.key} className="min-w-0">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: group.color }} />
                      {group.label}
                    </div>
                    <div className="mt-2 space-y-1">
                      {rows.length === 0 ? (
                        <span className="text-xs text-muted-foreground">—</span>
                      ) : rows.map((row) => {
                        const selected = selectedFlowKey === flowNodeKey(row);
                        const RowIcon = categoryIconForSlug(row.icon || row.category_slug || "other");
                        return (
                          <div
                            key={row.name}
                            className={`group flex w-full items-center gap-1.5 rounded-lg px-1 py-1 transition ${selected ? "bg-primary/10" : "hover:bg-muted/35"}`}
                          >
                            <button
                              type="button"
                              className="flex min-w-0 flex-1 items-center gap-2 text-left"
                              data-flow-selection="true"
                              aria-pressed={selected}
                              onClick={(event) => {
                                event.stopPropagation();
                                toggleFlowSelection(row, "summary");
                              }}
                            >
                              <span
                                className="grid h-5 w-5 shrink-0 place-items-center rounded-md"
                                style={{
                                  background: row.category_slug
                                    ? categoryColor(
                                        row.category_slug,
                                        row.color_key || undefined,
                                        row.color || undefined,
                                      )
                                    : row.role === "income"
                                      ? themeHsl("accent")
                                      : row.role === "saving"
                                        ? themeHsl("flow-saving")
                                        : themeHsl("danger"),
                                  color: themeHsl("category-label-foreground"),
                                }}
                              >
                                {row.account_source ? (
                                  <AccountIcon source={row.account_source} provider={row.account_provider || undefined} className="h-3 w-3" />
                                ) : (
                                  <RowIcon className="h-3 w-3" strokeWidth={2.25} aria-hidden />
                                )}
                              </span>
                              <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{cleanFlowLabel(row.name)}</span>
                              <span className="shrink-0 text-xs font-semibold tabular-nums text-foreground">{formatMoney(row.amount, "EUR", i18n.language)}</span>
                            </button>
                            <button
                              type="button"
                              className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted-foreground/65 transition hover:bg-muted/45 hover:text-foreground"
                              title={t("dashboard.openTransactions")}
                              aria-label={`${t("dashboard.openTransactions")}: ${cleanFlowLabel(row.name)}`}
                              onClick={() => openFlowRowTransactions(row)}
                            >
                              <ArrowUpRight className="h-3 w-3" aria-hidden />
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="mt-3 min-h-[15rem] rounded-2xl border border-border/35 bg-background/25 p-3 sm:p-4">
            <p className="text-sm text-muted-foreground">{t("dashboard.flowEmpty")}</p>
          </div>
        )}
      </section>

      <section ref={(element) => { mobileChartSectionsRef.current[1] = element; }} className={`w-full shrink-0 snap-start pr-3 pt-2 md:w-auto md:shrink md:pr-0 ${desktopChartIndex !== 1 ? "md:hidden" : ""}`}>
        <div className="mb-4">
          <h3 className="inline-flex items-center gap-2 text-xl font-semibold"><ChartLine className="h-5 w-5 text-muted-foreground" aria-hidden />{t("dashboard.trend")}</h3>
        </div>
        {loading ? (
          <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : chartData.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("dashboard.empty")}</p>
        ) : (
          <>
            <div className="h-[22rem] overflow-hidden rounded-2xl border border-border/25 bg-card/10 px-1 pt-2 shadow-inner shadow-black/[0.02] sm:px-2 md:h-[28rem]">
              <ResponsiveContainer key={`trend-theme-${themeRevision}`} width="100%" height="100%">
                <BarChart
                  data={chartData}
                  barCategoryGap="24%"
                  barGap={4}
                  margin={isMobile
                    ? { left: 2, right: 8, top: 6, bottom: 0 }
                    : { left: 8, right: 12, top: 6, bottom: 0 }}
                  onClick={(state) => {
                    const activeLabel = (state as { activeLabel?: string | number } | undefined)?.activeLabel;
                    if (activeLabel === undefined || activeLabel === null) return;
                    const period = String(activeLabel);
                    setSelectedDistributionKey(null);
                    setSelectedPeriod((current) => current === period ? null : period);
                  }}
                >
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={themeHsl("border")} />
                  <XAxis dataKey="period" tick={{ fontSize: 11, fill: themeHsl("muted-foreground") }} />
                  <YAxis
                    hide={demoMode}
                    width={isMobile ? 32 : 60}
                    tick={{ fontSize: 11, fill: themeHsl("muted-foreground") }}
                    tickFormatter={(value: number) => compactAxisValue(value, i18n.language)}
                  />
                  {displayIncomeKeys.map((k, i) => (
                    <Bar
                      key={`income-${k}`}
                      dataKey={k}
                      stackId="income"
                      fill={themeHsl("accent")}
                      fillOpacity={0.62}
                      shape={stackShape(displayIncomeKeys, k, "income")}
                      isAnimationActive={false}
                    >
                      {chartData.map((row) => {
                        const selected = selectedPeriod === row.period;
                        const dimmed = selectedPeriod !== null && !selected;
                        return (
                          <Cell
                            key={`${k}-${row.period}`}
                            fill={selected ? chartSeriesColor(k, i) : themeHsl("accent")}
                            fillOpacity={dimmed ? 0.14 : selectedPeriod !== null ? 0.82 : 0.62}
                          />
                        );
                      })}
                    </Bar>
                  ))}
                  {displayExpenseKeys.map((k, i) => (
                    <Bar
                      key={`expense-${k}`}
                      dataKey={k}
                      stackId="expense"
                      fill={themeHsl("danger")}
                      fillOpacity={0.72}
                      shape={stackShape(displayExpenseKeys, k, "expense")}
                      isAnimationActive={false}
                    >
                      {chartData.map((row) => {
                        const selected = selectedPeriod === row.period;
                        const dimmed = selectedPeriod !== null && !selected;
                        return (
                          <Cell
                            key={`${k}-${row.period}`}
                            fill={selected ? chartSeriesColor(k, i) : themeHsl("danger")}
                            fillOpacity={dimmed ? 0.14 : selectedPeriod !== null ? 0.86 : 0.72}
                          />
                        );
                      })}
                    </Bar>
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
            {selectedTrendRow && (
              <div className="mt-3 min-h-[15rem] rounded-2xl border border-border/35 bg-background/25 p-3 sm:p-4">
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-foreground">{selectedTrendRow.period}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{t("dashboard.trendSelectionHint")}</p>
                  </div>
                  <button
                    type="button"
                    className="rounded-full px-2 py-1 text-lg leading-none text-muted-foreground transition hover:bg-muted/60 hover:text-foreground"
                    onClick={() => setSelectedPeriod(null)}
                    aria-label={t("dashboard.clearSelection")}
                  >
                    ×
                  </button>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {[
                    { label: t("dashboard.income"), color: themeHsl("accent"), segments: selectedIncomeSegments },
                    { label: t("dashboard.expenses"), color: themeHsl("danger"), segments: selectedExpenseSegments },
                  ].map((group) => (
                    <div key={group.label} className="min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-foreground">
                          <span className="h-2 w-2 rounded-full" style={{ background: group.color }} />
                          {group.label}
                        </span>
                        <span className="text-xs font-semibold tabular-nums text-foreground">
                          {formatMoney(group.segments.reduce((sum, segment) => sum + segment.amount, 0), "EUR", i18n.language)}
                        </span>
                      </div>
                      <div className="mt-2 space-y-1.5">
                        {group.segments.length === 0 ? (
                          <span className="text-xs text-muted-foreground">—</span>
                        ) : group.segments.map((segment) => (
                          <button
                            key={segment.key}
                            type="button"
                            className="group flex w-full items-center gap-2 rounded-lg px-1 py-0.5 text-left text-xs transition hover:bg-muted/40"
                            title={t("dashboard.openTransactions")}
                            onClick={() => {
                              const label = segment.key.slice(2);
                              if (groupBy === "category") {
                                openTransactions({
                                  category: label,
                                  kind: segment.key.startsWith("i:") ? "income" : "expense",
                                });
                              } else {
                                openTransactions({
                                  account: label,
                                  kind: segment.key.startsWith("i:") ? "income" : "expense",
                                });
                              }
                            }}
                          >
                            {(() => {
                              const SegmentIcon = chartSegmentIcon(segment.key);
                              const label = segment.key.slice(2);
                              const accountMeta = groupBy === "account"
                                ? accountMetaByName.get(label.trim().toLocaleLowerCase())
                                : undefined;
                              const segmentColor = chartSeriesColor(segment.key, segment.index);
                              return (
                                <span
                                  className="grid h-5 w-5 shrink-0 place-items-center rounded-md"
                                  style={{ background: segmentColor, color: themeHsl("category-label-foreground") }}
                                >
                                  {accountMeta ? (
                                    <AccountIcon
                                      source={accountMeta.source}
                                      provider={accountMeta.provider}
                                      accountType={accountMeta.accountType}
                                      className="h-3 w-3"
                                    />
                                  ) : (
                                    <SegmentIcon className="h-3 w-3" strokeWidth={2.25} aria-hidden />
                                  )}
                                </span>
                              );
                            })()}
                            <span className="min-w-0 flex-1 truncate text-muted-foreground">{segment.key.slice(2)}</span>
                            <span className="shrink-0 font-semibold tabular-nums text-foreground">{formatMoney(segment.amount, "EUR", i18n.language)}</span>
                            <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60 transition group-hover:text-foreground" aria-hidden />
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {!selectedTrendRow && (
              <div className="mt-3 min-h-[15rem] rounded-2xl border border-border/35 bg-background/25 px-3 py-2.5">
                <p className="text-xs text-muted-foreground">{t("dashboard.trendHint")}</p>
              </div>
            )}
          </>
        )}
      </section>
      <section ref={(element) => { mobileChartSectionsRef.current[2] = element; }} className={`w-full shrink-0 snap-start pr-3 pt-2 md:w-auto md:shrink md:pr-0 ${desktopChartIndex !== 2 ? "md:hidden" : ""}`}>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h3 className="inline-flex items-center gap-2 text-xl font-semibold"><ChartPie className="h-5 w-5 text-muted-foreground" aria-hidden />{t("dashboard.distribution")}</h3>
          <div className="inline-flex rounded-xl border border-border/40 bg-background/25 p-0.5 md:hidden" role="group" aria-label={t("dashboard.distribution")}>
            {distributionGroups.map((group) => (
              <button
                key={group.key}
                type="button"
                className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[0.68rem] font-medium transition ${distributionMode === group.key ? "bg-foreground/10 text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                aria-pressed={distributionMode === group.key}
                onClick={() => {
                  setDistributionMode(group.key);
                  setSelectedDistributionKey(null);
                }}
              >
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: group.key === "income" ? themeHsl("accent") : themeHsl("danger") }}
                  aria-hidden
                />
                {group.label}
              </button>
            ))}
          </div>
        </div>
        {distributionGroups.every((group) => group.data.length === 0) ? (
          <p className="text-sm text-muted-foreground">{t("dashboard.empty")}</p>
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              {distributionGroups.map((group) => (
                <div key={group.key} className={`${group.key === distributionMode ? "" : "hidden md:block"} min-w-0`}>
                  <div className="mb-2 hidden items-center gap-1.5 text-xs font-semibold text-foreground md:flex">
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ background: group.key === "income" ? themeHsl("accent") : themeHsl("danger") }}
                    />
                    {group.label}
                  </div>
                  {group.data.length === 0 ? (
                    <div className="flex h-[22rem] items-center justify-center rounded-2xl border border-border/25 bg-card/10 px-3 text-xs text-muted-foreground md:h-[28rem]">
                      {t("dashboard.empty")}
                    </div>
                  ) : (
                    <div className="relative -mx-1 h-[22rem] w-[calc(100%+0.5rem)] rounded-2xl border border-border/25 bg-card/10 px-0 py-2 shadow-inner shadow-black/[0.02] sm:mx-0 sm:w-auto sm:px-1 md:h-[28rem]">
                      <ResponsiveContainer key={`distribution-${group.key}-${themeRevision}`} width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={group.data}
                            dataKey="value"
                            nameKey="name"
                            innerRadius={isMobile ? "31%" : "40%"}
                            outerRadius={isMobile ? "42%" : "58%"}
                            startAngle={0}
                            endAngle={360}
                            minAngle={1.5}
                            cornerRadius={3}
                            paddingAngle={1}
                            stroke={themeHsl("card")}
                            strokeWidth={2}
                            label={renderDistributionLabel(group.data, group.layout)}
                            labelLine={false}
                            style={{ cursor: "pointer" }}
                            isAnimationActive={false}
                            onClick={(_, index) => {
                              if (typeof index !== "number") return;
                              const entry = group.data[index];
                              if (!entry) return;
                              setDistributionMode(group.key);
                              setSelectedDistributionKey((current) => current === entry.key ? null : entry.key);
                            }}
                          >
                            {group.data.map((entry) => {
                              const selected = selectedDistributionKey === entry.key;
                              const dimmed = selectedDistributionKey !== null && !selected;
                              return (
                                <Cell
                                  key={entry.key}
                                  fill={chartSeriesColor(entry.key, entry.index)}
                                  fillOpacity={dimmed ? 0.16 : selected ? 1 : 0.84}
                                  strokeOpacity={dimmed ? 0.2 : 0.9}
                                />
                              );
                            })}
                          </Pie>
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="mt-3 min-h-[15rem] rounded-2xl border border-border/35 bg-background/25 p-3 sm:p-4">
              <div className="grid gap-4 sm:grid-cols-2">
                {distributionGroups.map((group) => (
                  <div key={group.key} className={`${group.key === distributionMode ? "" : "hidden md:block"} min-w-0`}>
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ background: group.key === "income" ? themeHsl("accent") : themeHsl("danger") }}
                      />
                      {group.label}
                    </div>
                    <div className="mt-2 space-y-1.5">
                      {group.data.length === 0 ? (
                        <span className="text-xs text-muted-foreground">—</span>
                      ) : group.data.map((entry) => {
                        const SegmentIcon = chartSegmentIcon(entry.key);
                        const accountMeta = groupBy === "account"
                          ? accountMetaByName.get(entry.name.trim().toLocaleLowerCase())
                          : undefined;
                        const segmentColor = chartSeriesColor(entry.key, entry.index);
                        const selected = selectedDistributionKey === entry.key;
                        return (
                          <div
                            key={entry.key}
                            className={`group flex w-full items-center gap-1.5 rounded-lg px-1 py-1 text-left transition ${selected ? "bg-primary/10" : "hover:bg-muted/35"}`}
                          >
                            <button
                              type="button"
                              className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                              aria-pressed={selected}
                              onClick={() => {
                                setDistributionMode(group.key);
                                setSelectedDistributionKey((current) => current === entry.key ? null : entry.key);
                              }}
                            >
                              <span
                                className="grid h-5 w-5 shrink-0 place-items-center rounded-md"
                                style={{ background: segmentColor, color: themeHsl("category-label-foreground") }}
                              >
                                {accountMeta ? (
                                  <AccountIcon
                                    source={accountMeta.source}
                                    provider={accountMeta.provider}
                                    accountType={accountMeta.accountType}
                                    className="h-3 w-3"
                                  />
                                ) : (
                                  <SegmentIcon className="h-3 w-3" strokeWidth={2.25} aria-hidden />
                                )}
                              </span>
                              <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{entry.name}</span>
                              <span className="shrink-0 text-xs font-semibold tabular-nums text-foreground">
                                {formatMoney(entry.value, "EUR", i18n.language)}
                              </span>
                            </button>
                            <button
                              type="button"
                              className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted-foreground/65 transition hover:bg-muted/45 hover:text-foreground"
                              title={t("dashboard.openTransactions")}
                              aria-label={`${t("dashboard.openTransactions")}: ${entry.name}`}
                              onClick={() => openTransactions(
                                groupBy === "account"
                                  ? { account: entry.name, kind: group.key }
                                  : { category: entry.name, kind: group.key }
                              )}
                            >
                              <ArrowUpRight className="h-3 w-3" aria-hidden />
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </section>
      </div>
      <div className="flex items-center justify-center gap-2 md:hidden" aria-label={t("dashboard.chartViews")}>
        {chartViews.map(({ index, label }) => (
          <button
            key={index}
            type="button"
            className={`h-1.5 rounded-full transition-all ${mobileChartIndex === index ? "w-6 bg-primary" : "w-1.5 bg-muted-foreground/35"}`}
            onClick={() => selectMobileChart(index)}
            aria-label={label}
            title={label}
            aria-current={mobileChartIndex === index ? "true" : undefined}
          />
        ))}
      </div>
      </Card>
      {advanced && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/25 p-4 backdrop-blur-sm"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setAdvanced(false);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="dashboard-filter-title"
            className="w-full max-w-md rounded-[1.5rem] border border-white/45 bg-card/95 p-4 text-card-foreground shadow-[0_24px_70px_-30px_hsl(var(--glass-shadow)/0.85)] backdrop-blur-2xl sm:p-5"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 id="dashboard-filter-title" className="text-base font-semibold text-foreground">
                  {t("dashboard.advanced")}
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("dashboard.periodHint", { from: t("dashboard.periodFrom"), to: t("dashboard.periodTo") })}
                </p>
              </div>
              <button
                type="button"
                className="grid h-8 w-8 place-items-center rounded-full text-lg leading-none text-muted-foreground transition hover:bg-muted/55 hover:text-foreground"
                onClick={() => setAdvanced(false)}
                aria-label={t("common.close")}
              >
                ×
              </button>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="min-w-0 space-y-1.5">
                <span className="block px-1 text-xs font-medium text-muted-foreground">{t("dashboard.periodFrom")}</span>
                <Input
                  className="min-w-0"
                  type="date"
                  aria-label={t("dashboard.periodFrom")}
                  max={customTo && customTo < todayValue ? customTo : todayValue}
                  value={customFrom}
                  onChange={(event) => {
                    const value = event.target.value > todayValue ? todayValue : event.target.value;
                    setCustomFrom(value);
                    if (customTo && value > customTo) setCustomTo(value);
                  }}
                />
              </label>
              <label className="min-w-0 space-y-1.5">
                <span className="block px-1 text-xs font-medium text-muted-foreground">{t("dashboard.periodTo")}</span>
                <Input
                  className="min-w-0"
                  type="date"
                  aria-label={t("dashboard.periodTo")}
                  min={customFrom || undefined}
                  max={todayValue}
                  value={customTo}
                  onChange={(event) => {
                    const value = event.target.value > todayValue ? todayValue : event.target.value;
                    setCustomTo(value);
                    if (customFrom && value < customFrom) setCustomFrom(value);
                  }}
                />
              </label>
            </div>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                className="rounded-xl border border-border/50 px-3 py-2 text-xs font-semibold text-muted-foreground transition hover:bg-muted/45 hover:text-foreground"
                onClick={() => {
                  setCustomFrom("");
                  setCustomTo("");
                  setAdvanced(false);
                }}
              >
                {t("dashboard.filterReset")}
              </button>
              <button
                type="button"
                className="rounded-xl bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground shadow-sm transition hover:brightness-105"
                onClick={() => setAdvanced(false)}
              >
                {t("dashboard.filterDone")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
