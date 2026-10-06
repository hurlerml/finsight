import { memo, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ChartNoAxesCombined, ChevronDown, ChevronRight, CircleDollarSign, Info, Landmark, Loader2 } from "lucide-react";
import {
  Area,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, type AssetHistory, type AssetsOverview, type InflationSeries } from "@/api/client";
import { useAppSetup } from "@/auth/AppSetupContext";
import { Select } from "@/components/ui";
import { isDemoModeEnabled, scaleDemoMoney } from "@/lib/demo";
import { AccountIcon } from "@/lib/icons";
import { cn, formatMoney } from "@/lib/utils";

const PERIODS = ["1d", "5d", "1m", "1y", "max"] as const;
type Period = (typeof PERIODS)[number];
type InstrumentChartMode = "performance" | "price";

// German consumer-price index (2021 = 100), kept local so chart rendering
// remains available offline. Annual values are rebased from Destatis' official
// 2020=100 series; monthly interpolation is only a temporary fallback until
// the backend stores the official monthly GENESIS observations.
const CPI_INDEX: Record<number, number> = {
  2021: 100,
  2022: 106.79,
  2023: 113.19,
  2024: 115.71,
  2025: 118.33,
};

function cpiAt(date: Date) {
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  const knownYears = Object.keys(CPI_INDEX).map(Number).sort((a, b) => a - b);
  if (year <= knownYears[0]) return CPI_INDEX[knownYears[0]];
  if (year >= knownYears[knownYears.length - 1]) return CPI_INDEX[knownYears[knownYears.length - 1]];
  const lowerYear = Math.max(...knownYears.filter((item) => item <= year));
  const upperYear = Math.min(...knownYears.filter((item) => item > year));
  const progress = (month + 0.5) / 12;
  return CPI_INDEX[lowerYear] + (CPI_INDEX[upperYear] - CPI_INDEX[lowerYear]) * progress;
}

function inflationFactor(date: Date, referenceDate: Date, series: InflationSeries | null) {
  if (!series?.points.length) return cpiAt(referenceDate) / cpiAt(date);
  const indexAt = (value: Date) => {
    const key = `${value.getUTCFullYear()}-${String(value.getUTCMonth() + 1).padStart(2, "0")}`;
    const exact = series.points.find((point) => point.month === key);
    if (exact) return Number(exact.index);
    const sorted = series.points;
    const prior = [...sorted].reverse().find((point) => point.month <= key);
    return prior ? Number(prior.index) : Number(sorted[0].index);
  };
  return indexAt(referenceDate) / indexAt(date);
}

function formatQuantity(value: string, language: string) {
  const raw = Number(value);
  const displayed = isDemoModeEnabled() ? (scaleDemoMoney(raw) ?? 0) : raw;
  return new Intl.NumberFormat(language, { maximumFractionDigits: 6 }).format(displayed);
}

type AssetActiveDotProps = {
  cx?: number;
  cy?: number;
  payload?: { performance?: number | null };
  showsPerformance: boolean;
};

type AssetTooltipProps = {
  active?: boolean;
  label?: number;
  payload?: Array<{ value?: unknown; name?: unknown; payload?: { performance?: number | null; performancePercent?: number | null } }>;
  currency: string;
  language: string;
  period: Period;
  fallbackCost?: number;
};

function AssetTooltip({ active, label, payload, currency, language, period, fallbackCost = 0 }: AssetTooltipProps) {
  if (!active || !payload?.length) return null;
  const item = payload[0];
  const amount = Number(item.value ?? 0);
  const performance = item.payload?.performance;
  const percent = item.payload?.performancePercent ?? (performance != null && fallbackCost > 0 ? (performance / fallbackCost) * 100 : null);
  const isNegative = performance != null && performance < 0;
  return (
    <div className="rounded-2xl border border-border/60 bg-card/95 px-3 py-2.5 text-xs shadow-xl backdrop-blur-md">
      {label != null && <p className="mb-1.5 text-[0.68rem] text-muted-foreground">{new Intl.DateTimeFormat(language, { dateStyle: "medium", timeStyle: period === "1d" || period === "5d" ? "short" : undefined }).format(new Date(label))}</p>}
      <p className={cn("font-semibold tabular-nums", isNegative ? "text-danger" : "text-accent")}>
        {formatMoney(amount, currency, language)}
        {percent != null && <> <span className="font-medium">({percent >= 0 ? "+" : ""}{percent.toLocaleString(language, { maximumFractionDigits: 2 })} %)</span></>}
      </p>
      {item.name != null && <p className="mt-0.5 text-[0.68rem] text-muted-foreground">{String(item.name)}</p>}
    </div>
  );
}

type AssetChartPoint = {
  timestamp: number;
  value: number;
  invested: number | null;
  performance: number | null;
  performancePercent: number | null;
};

function toAssetChartData(
  source: AssetHistory | null,
  options: {
    inflationAdjusted: boolean;
    inflationSeries: InflationSeries | null;
    performanceCost: number;
  },
): AssetChartPoint[] {
  if (!source) return [];
  const isInstrument = source.kind === "instrument";
  const isProviderPerformance = source.kind === "portfolio" && source.source === "provider";
  const referenceDate = new Date();
  return source.points.map((point) => {
    const timestamp = new Date(point.timestamp).getTime();
    const nominalValue = Number(point.value);
    const nominalInvested = point.invested_value == null ? null : Number(point.invested_value);
    const factor = options.inflationAdjusted
      ? inflationFactor(new Date(timestamp), referenceDate, options.inflationSeries)
      : 1;
    const value = nominalValue * factor;
    const invested = nominalInvested == null ? null : nominalInvested * factor;
    const providerPercent = point.performance_percent == null
      ? null
      : Number(point.performance_percent);
    const portfolioPercentCost = options.performanceCost > 0
      ? options.performanceCost * factor
      : null;
    return {
      timestamp,
      value,
      invested,
      performance: isProviderPerformance ? value : invested == null ? null : value - invested,
      performancePercent: isProviderPerformance
        ? providerPercent
        : isInstrument
          ? invested && invested !== 0 ? ((value - invested) / invested) * 100 : null
          : portfolioPercentCost && portfolioPercentCost !== 0 && invested != null
            ? (((value - invested) / portfolioPercentCost) * 100)
            : null,
    };
  });
}

function AssetActiveDot({ cx, cy, payload, showsPerformance }: AssetActiveDotProps) {
  if (cx == null || cy == null) return null;
  const negative = showsPerformance && (payload?.performance ?? 0) < 0;
  return (
    <circle
      cx={cx}
      cy={cy}
      r={4}
      fill={negative ? "hsl(var(--danger))" : "hsl(var(--accent))"}
      stroke="hsl(var(--card))"
      strokeWidth={1.5}
    />
  );
}

export const AssetsPage = memo(function AssetsPage() {
  const { t, i18n } = useTranslation();
  const { hasAccounts, accountSetupInProgress } = useAppSetup();
  const [data, setData] = useState<AssetsOverview | null>(null);
  const [inflationSeries, setInflationSeries] = useState<InflationSeries | null>(null);
  const [history, setHistory] = useState<AssetHistory | null>(null);
  const [scaleHistory, setScaleHistory] = useState<AssetHistory | null>(null);
  const [chartPortfolioId, setChartPortfolioId] = useState<number | null>(null);
  const [externalId, setExternalId] = useState("");
  const [period, setPeriod] = useState<Period>("max");
  const [inflationAdjusted, setInflationAdjusted] = useState(false);
  const [inflationInfoOpen, setInflationInfoOpen] = useState(false);
  const [collapsedPortfolios, setCollapsedPortfolios] = useState<Set<number>>(new Set());
  const [instrumentChartMode] = useState<InstrumentChartMode>("performance");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!hasAccounts) {
      setData({ portfolios: [] });
      return;
    }
    let cancelled = false;
    api.assets()
      .then((overview) => {
        if (cancelled) return;
        setData(overview);
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [hasAccounts]);

  useEffect(() => {
    api.germanyInflation().then(setInflationSeries).catch(() => setInflationSeries(null));
  }, []);

  useEffect(() => {
    if (!hasAccounts) {
      setHistory(null);
      setHistoryLoading(false);
      return;
    }
    const params = new URLSearchParams({ range: period });
    if (chartPortfolioId != null) params.set("portfolio_id", String(chartPortfolioId));
    if (chartPortfolioId != null && externalId) params.set("external_id", externalId);
    setHistoryLoading(true);
    api.assetHistory(params)
      .then(setHistory)
      .catch((err: Error) => setError(err.message))
      .finally(() => setHistoryLoading(false));
  }, [hasAccounts, chartPortfolioId, externalId, period]);

  // Keep a full-history copy for the chart scale. The selected range controls
  // which points are visible, but never rebases the zero line or the green /
  // red transition to that shorter range.
  useEffect(() => {
    if (!hasAccounts) {
      setScaleHistory(null);
      return;
    }
    let cancelled = false;
    const params = new URLSearchParams({ range: "max" });
    if (chartPortfolioId != null) params.set("portfolio_id", String(chartPortfolioId));
    if (chartPortfolioId != null && externalId) params.set("external_id", externalId);
    api.assetHistory(params)
      .then((result) => {
        if (!cancelled) setScaleHistory(result);
      })
      .catch(() => {
        if (!cancelled) setScaleHistory(null);
      });
    return () => {
      cancelled = true;
    };
  }, [hasAccounts, chartPortfolioId, externalId]);

  const totals = useMemo(() => {
    const portfolios = (data?.portfolios || []).filter(
      (portfolio) => chartPortfolioId == null || portfolio.id === chartPortfolioId
    );
    return portfolios.reduce(
      (sum, portfolio) => ({
      market: sum.market + Number(portfolio.total_market_value),
      cost: sum.cost + Number(portfolio.total_cost_value),
        performanceCost: sum.performanceCost + Number(portfolio.performance_cost_value || portfolio.total_cost_value),
        gain: sum.gain + Number(portfolio.total_gain_value),
      }),
      { market: 0, cost: 0, performanceCost: 0, gain: 0 }
    );
  }, [data, chartPortfolioId]);
  const totalGain = totals.gain;
  const selectedPortfolio = useMemo(
    () =>
      data?.portfolios.find(
        (portfolio) => chartPortfolioId == null || portfolio.id === chartPortfolioId
      ) ?? null,
    [data, chartPortfolioId]
  );
  // Trade Republic's relative performance is time-weighted and therefore
  // cannot be recreated from the current cost basis.  Use the provider value
  // whenever one portfolio is selected; aggregate views continue to use the
  // weighted local calculation below.
  const totalGainPercent =
    selectedPortfolio &&
    (chartPortfolioId != null || data?.portfolios.length === 1) &&
    selectedPortfolio.total_gain_percent != null
      ? Number(selectedPortfolio.total_gain_percent)
      : totals.performanceCost > 0
        ? (totalGain / totals.performanceCost) * 100
        : null;
  const isInstrument = history?.kind === "instrument";
  const isProviderPerformance = history?.kind === "portfolio" && history.source === "provider";
  const chartData = useMemo(() => {
    return toAssetChartData(history, {
      inflationAdjusted,
      inflationSeries,
      performanceCost: totals.performanceCost,
    });
  }, [history, inflationAdjusted, inflationSeries, isInstrument, isProviderPerformance, totals.performanceCost]);
  const scaleChartData = useMemo(() => {
    const source = period === "max" ? history : scaleHistory || history;
    return toAssetChartData(source, {
      inflationAdjusted,
      inflationSeries,
      performanceCost: totals.performanceCost,
    });
  }, [history, scaleHistory, period, inflationAdjusted, inflationSeries, totals.performanceCost]);
  const hasInvestedLine = chartData.some((point) => point.invested != null);
  const showsPerformance = hasInvestedLine || isProviderPerformance;
  // Provider performance series are already net P/L values with zero as the
  // break-even baseline. Keep the reference line visible for those series as
  // well; it is only the local cost-basis calculation that must not be drawn
  // on top of provider data.
  const showsBreakEven = hasInvestedLine || isProviderPerformance;
  const entryValue = useMemo(() => {
    if (!isInstrument) return null;
    const position = data?.portfolios
      .find((portfolio) => portfolio.id === chartPortfolioId)
      ?.positions.find((item) => item.external_id === externalId);
    const fromPosition = position?.average_buy_in && position.quantity
      ? Number(position.average_buy_in) * Number(position.quantity)
      : null;
    return fromPosition ?? chartData.find((point) => point.invested != null)?.invested ?? null;
  }, [data, chartData, chartPortfolioId, externalId, isInstrument]);
  const performanceValues = scaleChartData
    .map((point) => point.performance)
    .filter((value): value is number => value != null);
  const performanceMin = performanceValues.length ? Math.min(...performanceValues) : 0;
  const performanceMax = performanceValues.length ? Math.max(...performanceValues) : 0;
  const performanceDomain: [number | "auto", number | "auto"] = (() => {
    if (!performanceValues.length) return ["auto", "auto"];
    const min = Math.min(0, performanceMin);
    const max = Math.max(0, performanceMax);
    if (min === max) return [min - 1, max + 1];
    return [min, max];
  })();
  const performanceGradientOffset =
    performanceMax <= 0
      ? 0
      : performanceMin >= 0
        ? 1
        : performanceMax / (performanceMax - performanceMin);
  const portfolioWithCostBasis = data?.portfolios.find(
    (portfolio) => Number(portfolio.total_cost_value) > 0
  );

  if (!hasAccounts) {
    return (
      <div className="space-y-5">
        <div className="px-1">
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t("assets.title")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("assets.subtitle")}</p>
        </div>
        <div className="glass-surface rounded-[1.65rem] px-6 py-12 text-center sm:py-16">
          {accountSetupInProgress ? (
            <>
              <Loader2 className="mx-auto h-8 w-8 animate-spin text-primary" aria-hidden />
              <h3 className="mt-4 text-lg font-semibold">{t("assets.accountSyncInProgressTitle")}</h3>
              <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
                {t("assets.accountSyncInProgressHint")}
              </p>
            </>
          ) : (
            <>
              <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-muted/55 text-muted-foreground">
                <Landmark className="h-6 w-6" aria-hidden />
              </span>
              <h3 className="mt-4 text-lg font-semibold">{t("assets.noAccountsTitle")}</h3>
              <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
                {t("assets.noAccountsHint")}
              </p>
              <Link
                to="/accounts"
                className="mt-5 inline-flex min-h-11 items-center justify-center rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition hover:-translate-y-px hover:shadow-md"
              >
                {t("assets.addAccount")}
              </Link>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-4 px-1">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t("assets.title")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("assets.subtitle")}</p>
        </div>
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      {data && data.portfolios.length > 0 ? (
        <div className="glass-surface overflow-hidden rounded-[1.65rem] text-card-foreground">
          <div className="flex items-end justify-between gap-4 px-5 pb-5 pt-6 sm:px-6">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                {t("assets.investedValue")}
              </p>
              <p className="mt-1 text-3xl font-semibold tracking-tight tabular-nums sm:text-4xl">
                {formatMoney(totals.market, "EUR", i18n.language)}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm">
                <span className="text-muted-foreground">
                  {t("assets.costValue")} {" "}
                  <strong className="font-medium tabular-nums text-foreground">
                    {formatMoney(totals.cost, "EUR", i18n.language)}
                  </strong>
                </span>
                <span
                  className={cn(
                    "font-semibold tabular-nums",
                    totalGain >= 0 ? "text-accent" : "text-danger"
                  )}
                >
                  {totalGain >= 0 ? "+" : ""}
                  {formatMoney(totalGain, "EUR", i18n.language)}
                  {totalGainPercent != null && (
                    <> · {totalGainPercent >= 0 ? "+" : ""}{totalGainPercent.toLocaleString(i18n.language, { maximumFractionDigits: 2 })} %</>
                  )}
                </span>
              </div>
            </div>
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-accent/15 text-accent">
              <ChartNoAxesCombined className="h-5 w-5" aria-hidden />
            </span>
          </div>

          <div className="px-3 pb-5 sm:px-6">
            <div className="rounded-[1.35rem] border border-border/30 bg-card/10 px-3 pb-3 pt-3 sm:px-4">
              <div className="flex flex-wrap items-end justify-between gap-3 px-1">
                <div className="min-w-[10rem] flex-1 space-y-1">
                  <label className="block text-[0.65rem] font-medium uppercase tracking-[0.1em] text-muted-foreground">
                    {t("assets.chartScope")}
                  </label>
                  <Select
                    aria-label={t("assets.historySelection")}
                    value={
                      chartPortfolioId == null
                        ? "all:"
                        : `${chartPortfolioId}:${externalId}`
                    }
                    onChange={(event) => {
                      const [nextPortfolioId, ...instrumentParts] = event.target.value.split(":");
                      setChartPortfolioId(
                        nextPortfolioId === "all" ? null : Number(nextPortfolioId)
                      );
                      setExternalId(instrumentParts.join(":"));
                    }}
                    className="h-9 max-w-sm truncate font-semibold"
                  >
                    <option value="all:">{t("assets.totalPortfolio")}</option>
                    {data.portfolios.map((portfolio) => (
                      <optgroup key={portfolio.id} label={portfolio.name}>
                        <option value={`${portfolio.id}:`}>
                          {t("assets.providerPortfolio", { name: portfolio.name })}
                        </option>
                        {portfolio.positions.map((position) => (
                          <option
                            key={`${portfolio.id}:${position.external_id}`}
                            value={`${portfolio.id}:${position.external_id}`}
                          >
                            {position.name}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </Select>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  {showsPerformance && !isInstrument && instrumentChartMode !== "price" && (
                    <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full bg-muted/45 px-2.5 text-[0.68rem] font-semibold text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={inflationAdjusted}
                        onChange={(event) => setInflationAdjusted(event.target.checked)}
                        className="h-3.5 w-3.5 accent-[hsl(var(--accent))]"
                      />
                      {t("assets.inflationAdjusted")}
                    </label>
                  )}
                  <div className="flex rounded-full bg-muted/45 p-0.5">
                  {PERIODS.map((item) => (
                    <button
                      key={item}
                      type="button"
                      onClick={() => setPeriod(item)}
                      className={cn(
                        "min-w-8 rounded-full px-2 py-1 text-[0.68rem] font-semibold transition-colors",
                        period === item
                          ? "bg-card text-foreground shadow-sm"
                          : "text-muted-foreground"
                      )}
                    >
                      {t(`assets.periods.${item}`)}
                    </button>
                  ))}
                  </div>
                </div>
              </div>

              <div className="mt-3 flex items-center gap-4 px-1 text-[0.68rem] text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-accent" />
                  {instrumentChartMode === "price" && isInstrument
                    ? t("assets.price")
                    : inflationAdjusted && showsPerformance && !isInstrument
                    ? t("assets.realPerformance")
                    : showsPerformance
                      ? t("assets.performance")
                      : t("assets.portfolioValue")}
                </span>
                {showsBreakEven && (
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-px w-3 bg-muted-foreground/70" />
                    {t("assets.breakEven")}
                  </span>
                )}
              </div>
              {!historyLoading && history?.kind === "aggregate" && !hasInvestedLine && portfolioWithCostBasis && (
                <button
                  type="button"
                  onClick={() => {
                    setChartPortfolioId(portfolioWithCostBasis.id);
                    setExternalId("");
                  }}
                  className="mx-1 mt-2 text-left text-[0.68rem] font-medium text-warning transition-colors hover:text-foreground"
                >
                  {t("assets.investedCapitalIncomplete", {
                    name: portfolioWithCostBasis.name,
                  })}
                </button>
              )}

              <div className="mt-2 h-52 w-full sm:h-64">
                {historyLoading ? (
                  <div className="grid h-full place-items-center text-sm text-muted-foreground">
                    {t("common.loading")}
                  </div>
                ) : chartData.length > 1 && history ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={chartData} margin={{ left: 0, right: 8, top: 10, bottom: 0 }}>
                      <defs>
                        <linearGradient id="assetHistoryFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.28} />
                          <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0.01} />
                        </linearGradient>
                        <linearGradient id="assetPerformanceStroke" x1="0" y1="0" x2="0" y2="1">
                          <stop offset={performanceGradientOffset} stopColor="hsl(var(--accent))" />
                          <stop offset={performanceGradientOffset} stopColor="hsl(var(--danger))" />
                        </linearGradient>
                        <linearGradient id="assetPerformanceFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.2} />
                          <stop offset={performanceGradientOffset} stopColor="hsl(var(--accent))" stopOpacity={0.025} />
                          <stop offset={performanceGradientOffset} stopColor="hsl(var(--danger))" stopOpacity={0.025} />
                          <stop offset="100%" stopColor="hsl(var(--danger))" stopOpacity={0.2} />
                        </linearGradient>
                      </defs>
                      <XAxis
                        dataKey="timestamp"
                        type="number"
                        domain={["dataMin", "dataMax"]}
                        tickLine={false}
                        axisLine={false}
                        minTickGap={40}
                        tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                        tickFormatter={(value: number) =>
                          new Intl.DateTimeFormat(i18n.language, {
                            day: "2-digit",
                            month: "short",
                            ...(period === "max" || period === "1y" ? { year: "2-digit" } : {}),
                          }).format(new Date(value))
                        }
                      />
                      <YAxis
                        hide
                        domain={showsPerformance ? performanceDomain : ["auto", "auto"]}
                      />
                      <Tooltip
                        cursor={{ stroke: "hsl(var(--border))" }}
                        content={(props) => <AssetTooltip {...props} currency={history.currency} language={i18n.language} period={period} fallbackCost={totals.performanceCost} />}
                      />
                      <Area
                        type="linear"
                        dataKey={instrumentChartMode === "price" && isInstrument ? "value" : showsPerformance ? "performance" : "value"}
                        stroke={instrumentChartMode === "price" && isInstrument ? "hsl(var(--accent))" : showsPerformance ? "url(#assetPerformanceStroke)" : "hsl(var(--accent))"}
                        strokeWidth={2.25}
                        fill={instrumentChartMode === "price" && isInstrument ? "url(#assetHistoryFill)" : showsPerformance ? "url(#assetPerformanceFill)" : "url(#assetHistoryFill)"}
                        dot={false}
                        activeDot={(props) => (
                          <AssetActiveDot
                            {...props}
                            showsPerformance={showsPerformance && instrumentChartMode !== "price"}
                          />
                        )}
                        isAnimationActive={false}
                        name={
                          instrumentChartMode !== "price" && showsPerformance
                            ? inflationAdjusted
                              ? t("assets.realPerformance")
                              : t("assets.performance")
                            : history.kind === "instrument"
                              ? t("assets.price")
                              : t("assets.portfolioValue")
                        }
                      />
                      {instrumentChartMode === "price" && isInstrument && entryValue != null && (
                        <ReferenceLine
                          y={entryValue}
                          stroke="hsl(var(--muted-foreground))"
                          strokeDasharray="4 4"
                          strokeOpacity={0.8}
                          label={{ value: t("assets.entryPrice"), position: "insideTopRight", fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
                        />
                      )}
                      {instrumentChartMode !== "price" && showsBreakEven && (
                        <ReferenceLine
                          y={0}
                          stroke="hsl(var(--muted-foreground))"
                          strokeOpacity={0.66}
                          strokeWidth={1.5}
                          ifOverflow="extendDomain"
                        />
                      )}
                    </ComposedChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="grid h-full place-items-center px-6 text-center text-sm text-muted-foreground">
                    {t("assets.historyEmpty")}
                  </div>
                )}
              </div>
              {history?.estimated && (
                <p className="px-1 pb-1 pt-2 text-[0.68rem] leading-relaxed text-muted-foreground">
                  {t("assets.estimatedHistory")}
                </p>
              )}
              {inflationAdjusted && showsPerformance && !isInstrument && instrumentChartMode !== "price" && (
                <>
                  <button type="button" onClick={() => setInflationInfoOpen(true)} className="inline-flex items-center gap-1 px-1 pb-1 pt-2 text-[0.68rem] font-medium text-muted-foreground underline decoration-border underline-offset-2 hover:text-foreground"><Info className="h-3 w-3" aria-hidden />{t("assets.inflationExplain")}</button>
                  {inflationInfoOpen && <div className="fixed inset-0 z-50 grid place-items-center bg-black/25 p-4 backdrop-blur-sm" onMouseDown={(event) => { if (event.target === event.currentTarget) setInflationInfoOpen(false); }}><div role="dialog" aria-modal="true" aria-labelledby="inflation-info-title" className="w-full max-w-md rounded-[1.5rem] border border-border/50 bg-background/95 p-5 shadow-2xl"><div className="flex items-start justify-between gap-3"><div><h2 id="inflation-info-title" className="text-lg font-semibold">{t("assets.inflationTitle")}</h2><p className="mt-2 text-sm leading-relaxed text-muted-foreground">{t("assets.inflationMethod")}</p></div><button type="button" onClick={() => setInflationInfoOpen(false)} className="text-xl leading-none text-muted-foreground" aria-label={t("common.close")}>×</button></div><a href="https://ec.europa.eu/eurostat/en/web/products-datasets/-/PRC_HICP_MIDX" target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-foreground underline decoration-border underline-offset-2 hover:text-accent"><Info className="h-3 w-3" aria-hidden />{t("assets.inflationSource")}</a></div></div>}
                </>
              )}
            </div>
          </div>

          <div className="flex items-center justify-between px-5 py-3 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground sm:px-6">
            <span>Depot / Asset</span>
            <span>Seit Kauf</span>
          </div>

          {data.portfolios.map((portfolio) => (
            <section key={portfolio.id} className="border-t border-border/30 bg-muted/[0.08]">
              <button
                type="button"
                aria-expanded={!collapsedPortfolios.has(portfolio.id)}
                onClick={() => setCollapsedPortfolios((current) => {
                  const next = new Set(current);
                  if (next.has(portfolio.id)) next.delete(portfolio.id);
                  else next.add(portfolio.id);
                  return next;
                })}
                className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition-colors hover:bg-muted/15 sm:px-6"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span className="grid h-6 w-6 shrink-0 place-items-center text-muted-foreground" aria-hidden>
                    {collapsedPortfolios.has(portfolio.id) ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                  </span>
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-card/45 text-muted-foreground"><AccountIcon source={portfolio.source} provider={portfolio.source} /></span>
                  <div><h3 className="text-sm font-semibold">{portfolio.name}</h3>
                  <p className="text-xs text-muted-foreground">
                    {t("assets.positionsCount", {
                      count: portfolio.positions.length,
                    })}
                  </p></div>
                </div>
                <div className="shrink-0 text-right"><p className="text-sm font-semibold tabular-nums">{formatMoney(portfolio.total_gain_value, portfolio.currency, i18n.language)}</p><p className={cn("text-xs font-medium", Number(portfolio.total_gain_value) >= 0 ? "text-accent" : "text-danger")}>{Number(portfolio.total_gain_value) >= 0 ? "+" : ""}{(portfolio.total_gain_percent != null ? Number(portfolio.total_gain_percent) : (Number(portfolio.performance_cost_value) ? (Number(portfolio.total_gain_value) / Number(portfolio.performance_cost_value)) * 100 : 0)).toLocaleString(i18n.language, { maximumFractionDigits: 2 })} %</p></div>
              </button>

              {!collapsedPortfolios.has(portfolio.id) && <div className="ml-5 divide-y divide-border/30 border-l-2 border-border/35 sm:ml-8">
                {portfolio.positions.map((position) => {
                  const gain = position.gain_value == null ? null : Number(position.gain_value);
                  return (
                    <div
                      key={position.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => {
                        setChartPortfolioId(portfolio.id);
                        setExternalId(position.external_id);
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          setChartPortfolioId(portfolio.id);
                          setExternalId(position.external_id);
                        }
                      }}
                      className={cn(
                        "flex cursor-pointer items-center justify-between gap-3 px-4 py-3.5 transition-colors hover:bg-muted/20 sm:px-5",
                        chartPortfolioId === portfolio.id &&
                          externalId === position.external_id &&
                          "bg-accent/[0.06]"
                      )}
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-muted/55 text-muted-foreground">
                          <CircleDollarSign className="h-[1.15rem] w-[1.15rem]" aria-hidden />
                        </span>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{position.name}</p>
                          <p className="truncate text-xs text-muted-foreground">
                            {formatQuantity(position.quantity, i18n.language)} · {position.isin || position.external_id}
                          </p>
                        </div>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-sm font-semibold tabular-nums">
                          {position.market_value == null
                            ? t("common.emDash")
                            : formatMoney(position.market_value, position.currency, i18n.language)}
                        </p>
                        {gain != null && (gain !== 0 || Number(position.performance_cost_value) > 0) && (
                          <p
                            className={cn(
                              "text-xs font-medium tabular-nums",
                              gain >= 0 ? "text-accent" : "text-danger"
                            )}
                          >
                            {gain >= 0 ? "+" : ""}
                            {formatMoney(gain, position.currency, i18n.language)}
                            {position.gain_percent != null && (
                              <> · {Number(position.gain_percent) >= 0 ? "+" : ""}{Number(position.gain_percent).toLocaleString(i18n.language, { maximumFractionDigits: 2 })} %</>
                            )}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>}
            </section>
          ))}
        </div>
      ) : data ? (
        <div className="glass-surface rounded-[1.65rem] px-6 py-12 text-center">
          <ChartNoAxesCombined className="mx-auto h-8 w-8 text-muted-foreground" aria-hidden />
          <h3 className="mt-3 font-semibold">{t("assets.emptyTitle")}</h3>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
            {t("assets.emptyHint")}
          </p>
        </div>
      ) : (
        <p className="px-1 text-sm text-muted-foreground">{t("common.loading")}</p>
      )}
    </div>
  );
});
