import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { useTranslation } from "react-i18next";
import { ArrowDown, Check, Info, Link2, Loader2, PiggyBank, Search, SlidersHorizontal, X } from "lucide-react";
import { useOutletContext, useSearchParams } from "react-router-dom";

import {
  api,
  type Account,
  type Category,
  type Connection,
  type Tag,
  type Transaction,
  type TransactionGroup,
  type TransactionTag,
} from "@/api/client";
import { Badge, Button, Card, Input, Select } from "@/components/ui";
import type { LayoutOutletContext } from "@/components/Layout";
import { categoryColor } from "@/lib/colors";
import { AccountIcon, CategoryIcon } from "@/lib/icons";
import { formatMoney, monthRange, yearRange } from "@/lib/utils";

const PAGE_SIZE = 40;

function HighlightText({ value, query }: { value: string; query: string }) {
  const needle = query.trim();
  if (!needle) return <>{value}</>;
  const parts = value.split(new RegExp(`(${needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig"));
  return <>{parts.map((part, index) => part.toLowerCase() === needle.toLowerCase() ? <mark key={index} className="rounded bg-warning/35 text-inherit">{part}</mark> : part)}</>;
}

function useDesktopLayout() {
  const [isDesktop, setIsDesktop] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia("(min-width: 768px)").matches : false
  );

  useEffect(() => {
    const media = window.matchMedia("(min-width: 768px)");
    const update = () => setIsDesktop(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return isDesktop;
}

function eventTargetsControl(target: EventTarget | null) {
  return target instanceof Element && Boolean(
    target.closest("button, select, input, textarea, a, label")
  );
}

function openFromKeyboard(event: KeyboardEvent, open: () => void) {
  if (eventTargetsControl(event.target)) return;
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    open();
  }
}

function CategoryPicker({
  value,
  categories,
  emptyLabel,
  ariaLabel,
  onChange,
}: {
  value: number | null;
  categories: Category[];
  emptyLabel: string;
  ariaLabel: string;
  onChange: (value: string) => void;
}) {
  const selected = categories.find((category) => category.id === value);
  const color = selected
    ? categoryColor(selected.slug, selected.color_key, selected.color)
    : "hsl(var(--muted-foreground))";

  return (
    <label
      className="relative inline-flex max-w-full cursor-pointer items-center gap-1 overflow-hidden rounded-full px-2.5 py-0.5 text-xs font-medium transition hover:brightness-105"
      style={{
        color: selected ? "hsl(var(--category-label-foreground))" : "hsl(var(--muted-foreground))",
        background: selected
          ? color
          : "hsl(var(--muted) / 0.55)",
      }}
    >
      {selected && <CategoryIcon slug={selected.slug} icon={selected.icon} />}
      <span className="truncate">{selected?.name || emptyLabel}</span>
      <span className="shrink-0 text-[9px] leading-none opacity-60" aria-hidden>
        ▾
      </span>
      <select
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
        aria-label={ariaLabel}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{emptyLabel}</option>
        {categories.map((category) => (
          <option key={category.id} value={category.id}>{category.name}</option>
        ))}
      </select>
    </label>
  );
}

function TransactionKindBadge({ kind, label }: { kind: string; label: string }) {
  const color = kind === "income"
    ? "hsl(var(--accent))"
    : kind === "expense"
      ? "hsl(var(--danger))"
      : "hsl(var(--muted-foreground) / 0.65)";

  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} aria-hidden />
      <span>{label}</span>
    </span>
  );
}

function TransactionExplanationButton({
  transaction,
  label,
  onOpen,
}: {
  transaction: Pick<Transaction, "categorized_by" | "categorization_reason">;
  label: string;
  onOpen: () => void;
}) {
  const hasExplanation = transaction.categorized_by === "llm"
    || Boolean(transaction.categorization_reason?.trim());
  if (!hasExplanation) return null;
  return (
    <button
      type="button"
      className="inline-grid h-6 w-6 shrink-0 place-items-center rounded-full text-muted-foreground transition hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45"
      aria-label={label}
      title={label}
      aria-haspopup="dialog"
      onClick={(event) => {
        event.stopPropagation();
        onOpen();
      }}
    >
      <Info className="h-3.5 w-3.5" aria-hidden />
    </button>
  );
}

function transactionAmountColor(kind: string) {
  if (kind === "income") return "hsl(var(--accent))";
  if (kind === "expense") return "hsl(var(--danger))";
  return undefined;
}

function TransactionTags({
  tags,
  assigned,
  addLabel,
  onAdd,
  onRemove,
}: {
  tags: Tag[];
  assigned: Tag[];
  addLabel: string;
  onAdd: (tagId: number) => void;
  onRemove: (tagId: number) => void;
}) {
  const available = tags.filter((tag) => !assigned.some((item) => item.id === tag.id));
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {assigned.map((tag) => (
        <span
          key={tag.id}
          className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium text-slate-800"
          style={{ backgroundColor: tag.color }}
        >
          {tag.name}
          <button
            type="button"
            className="opacity-55 hover:opacity-100"
            onClick={() => onRemove(tag.id)}
            aria-label={`${tag.name} entfernen`}
          >
            ×
          </button>
        </span>
      ))}
      {available.length > 0 && (
        <label className="relative inline-flex cursor-pointer items-center rounded-full bg-muted/55 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
          + {addLabel}
          <select
            className="absolute inset-0 cursor-pointer opacity-0"
            value=""
            onChange={(event) => event.target.value && onAdd(Number(event.target.value))}
            aria-label={addLabel}
          >
            <option value="">{addLabel}</option>
            {available.map((tag) => <option key={tag.id} value={tag.id}>{tag.name}</option>)}
          </select>
        </label>
      )}
    </div>
  );
}

function TransactionGroupCard({
  group,
  categories,
  tags,
  tagsByTransaction,
  language,
  categoryLabel,
  explanationLabel,
  uncategorizedLabel,
  addTagLabel,
  transferLabel,
  brokerFundingLabel,
  fundingLabel,
  suggestionLabel,
  confirmLabel,
  rejectLabel,
  unlinkLabel,
  reviewing,
  onCategoryChange,
  onAddTag,
  onRemoveTag,
  onConfirm,
  onReject,
  onOpenTransaction,
}: {
  group: TransactionGroup;
  categories: Category[];
  tags: Tag[];
  tagsByTransaction: Record<number, Tag[]>;
  language: string;
  categoryLabel: string;
  explanationLabel: string;
  uncategorizedLabel: string;
  addTagLabel: string;
  transferLabel: string;
  brokerFundingLabel: string;
  fundingLabel: string;
  suggestionLabel: string;
  confirmLabel: string;
  rejectLabel: string;
  unlinkLabel: string;
  reviewing: boolean;
  onCategoryChange: (txId: number, categoryId: string) => void;
  onAddTag: (txId: number, tagId: number) => void;
  onRemoveTag: (txId: number, tagId: number) => void;
  onConfirm: () => void;
  onReject: () => void;
  onOpenTransaction: (transaction: Transaction) => void;
}) {
  const isBrokerFunding = group.link_type === "broker_funding";
  const isFunding = group.link_type !== "internal_transfer";
  const title = isBrokerFunding ? brokerFundingLabel : isFunding ? fundingLabel : transferLabel;
  return (
    <Card className={group.status === "suggested" ? "overflow-hidden border border-primary/30 p-0" : "overflow-hidden p-0"}>
      <div className="flex items-center justify-between gap-3 border-b border-border/45 bg-muted/25 px-4 py-3 sm:px-5">
        <div className="flex items-center gap-2">
          {isFunding ? (
            <PiggyBank className="h-4 w-4 text-muted-foreground" aria-hidden />
          ) : (
            <Link2 className="h-4 w-4 text-muted-foreground" aria-hidden />
          )}
          <span className="text-sm font-semibold">{title}</span>
        </div>
        <div className="flex items-center gap-2">
          {group.status === "suggested" && <Badge className="text-primary">{suggestionLabel}</Badge>}
          <Badge>{Math.round(Number(group.confidence) * 100)}%</Badge>
        </div>
      </div>
      <div className="relative px-4 py-3 sm:px-5">
        {group.reason && (
          <p className="mb-3 text-xs leading-relaxed text-muted-foreground">{group.reason}</p>
        )}
        {group.transactions.map((tx, index) => (
          <div key={tx.id}>
            {index > 0 && (
              <div className="flex h-8 items-center pl-[1.15rem]" aria-hidden>
                <div className="h-full w-px bg-border" />
                <ArrowDown className="-ml-2.5 h-4 w-4 rounded-full bg-card text-muted-foreground" />
              </div>
            )}
            <div
              className="flex cursor-pointer items-start gap-3 rounded-xl outline-none transition hover:bg-muted/20 focus-visible:ring-2 focus-visible:ring-ring/40"
              role="button"
              tabIndex={0}
              onClick={(event) => {
                if (!eventTargetsControl(event.target)) onOpenTransaction(tx);
              }}
              onKeyDown={(event) => openFromKeyboard(event, () => onOpenTransaction(tx))}
            >
              <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-muted/55 text-muted-foreground">
                <AccountIcon
                  source={tx.account_source}
                  provider={tx.account_provider || undefined}
                  accountType={tx.account_type}
                />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{tx.account_name}</p>
                    <div className="flex min-w-0 items-center gap-1.5">
                      <p className="min-w-0 truncate text-sm text-muted-foreground">
                        {tx.counterparty || tx.raw_text || "—"}
                      </p>
                      <TransactionExplanationButton
                        transaction={tx}
                        label={explanationLabel}
                        onOpen={() => onOpenTransaction(tx)}
                      />
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {tx.booking_date}
                    </p>
                  </div>
                  <p className="shrink-0 font-semibold tabular-nums">
                    {formatMoney(tx.amount, tx.currency, language)}
                  </p>
                </div>
                {tx.kind !== "transfer" && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <CategoryPicker
                      value={tx.category_id}
                      categories={categories}
                      emptyLabel={uncategorizedLabel}
                      ariaLabel={categoryLabel}
                      onChange={(value) => onCategoryChange(tx.id, value)}
                    />
                    <TransactionTags
                      tags={tags}
                      assigned={tagsByTransaction[tx.id] || []}
                      addLabel={addTagLabel}
                      onAdd={(tagId) => onAddTag(tx.id, tagId)}
                      onRemove={(tagId) => onRemoveTag(tx.id, tagId)}
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap justify-end gap-2 border-t border-border/45 bg-muted/15 px-4 py-3 sm:px-5">
        {group.status === "suggested" && (
          <Button type="button" className="gap-1.5" disabled={reviewing} onClick={onConfirm}>
            <Check className="h-4 w-4" aria-hidden />
            {confirmLabel}
          </Button>
        )}
        <Button
          type="button"
          variant={group.status === "suggested" ? "outline" : "ghost"}
          className="gap-1.5 text-muted-foreground"
          disabled={reviewing}
          onClick={onReject}
        >
          <X className="h-4 w-4" aria-hidden />
          {group.status === "suggested" ? rejectLabel : unlinkLabel}
        </Button>
      </div>
    </Card>
  );
}

export function TransactionsPage() {
  const { t, i18n } = useTranslation();
  const { assistant } = useOutletContext<LayoutOutletContext>();
  const now = new Date();
  const [searchParams] = useSearchParams();
  const queryFrom = searchParams.get("from");
  const queryTo = searchParams.get("to");
  const queryCategory = searchParams.get("category")?.trim() || "";
  const queryAccount = searchParams.get("account")?.trim() || "";
  const hasQueryRange = Boolean(queryFrom && queryTo);
  const [urlRange, setUrlRange] = useState<{ from: string; to: string } | null>(() =>
    hasQueryRange ? { from: queryFrom as string, to: queryTo as string } : null
  );
  const initialQueryDate = queryFrom ? new Date(`${queryFrom}T00:00:00`) : now;
  const sameQueryMonth = Boolean(
    queryFrom && queryTo && queryFrom.slice(0, 7) === queryTo.slice(0, 7)
  );
  const [year, setYear] = useState(initialQueryDate.getFullYear());
  const [month, setMonth] = useState(sameQueryMonth ? initialQueryDate.getMonth() + 1 : 0);
  const [kind, setKind] = useState(() => searchParams.get("kind") || "");
  const [accountId, setAccountId] = useState(() => {
    const value = searchParams.get("account_id");
    return value && /^\d+$/.test(value) ? value : "";
  });
  const [categoryId, setCategoryId] = useState(() => {
    const value = searchParams.get("category_id");
    return value && /^\d+$/.test(value) ? value : "";
  });
  const [txs, setTxs] = useState<Transaction[]>([]);
  const [transactionGroups, setTransactionGroups] = useState<TransactionGroup[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [tagAssignments, setTagAssignments] = useState<TransactionTag[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reviewingLinkId, setReviewingLinkId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState(() => searchParams.get("q") || "");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const nextOffsetRef = useRef(0);
  const requestVersionRef = useRef(0);
  const loadingMoreRef = useRef(false);
  const lastAppliedCategorizationRef = useRef<number | null>(null);
  const wasCategorizingRef = useRef(false);
  const categorizationRefreshTimerRef = useRef<number | undefined>(undefined);
  const loadMoreRef = useRef<HTMLDivElement>(null);
  const categoryQueryAppliedRef = useRef(false);
  const accountQueryAppliedRef = useRef(false);
  const isDesktop = useDesktopLayout();
  const categorizing = Boolean(
    assistant
    && (assistant.phase === "running" || assistant.phase === "researching" || assistant.phase === "waiting_ollama" || assistant.queue_remaining > 0)
  );
  const categorizationTotal = assistant?.queue_total || assistant?.queue_remaining || 0;
  const categorizationCurrent = Math.min(
    categorizationTotal,
    (assistant?.queue_processed || 0) + (assistant?.current ? 1 : 0)
  );

  useEffect(() => {
    if (!selectedTransaction) return;
    const scrollY = window.scrollY;
    const previous = {
      overflow: document.body.style.overflow,
      position: document.body.style.position,
      top: document.body.style.top,
      width: document.body.style.width,
    };
    document.body.style.overflow = "hidden";
    document.body.style.position = "fixed";
    document.body.style.top = `-${scrollY}px`;
    document.body.style.width = "100%";
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setSelectedTransaction(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      document.body.style.overflow = previous.overflow;
      document.body.style.position = previous.position;
      document.body.style.top = previous.top;
      document.body.style.width = previous.width;
      window.scrollTo(0, scrollY);
    };
  }, [selectedTransaction]);

  const range = useMemo(
    () => urlRange || (month === 0 ? yearRange(year) : monthRange(year, month)),
    [month, urlRange, year]
  );
  const catMap = useMemo(
    () => Object.fromEntries(categories.map((c) => [c.id, c])),
    [categories]
  );
  const accountMap = useMemo(
    () => Object.fromEntries(accounts.map((account) => [account.id, account])),
    [accounts]
  );
  const connectionMap = useMemo(
    () => Object.fromEntries(connections.map((connection) => [connection.id, connection])),
    [connections]
  );
  const tagsByTransaction = useMemo(() => {
    const tagMap = Object.fromEntries(tags.map((tag) => [tag.id, tag]));
    const grouped: Record<number, Tag[]> = {};
    for (const assignment of tagAssignments) {
      const tag = tagMap[assignment.tag_id];
      if (tag) (grouped[assignment.transaction_id] ||= []).push(tag);
    }
    return grouped;
  }, [tagAssignments, tags]);
  const loadedTransactionIds = useMemo(() => new Set(txs.map((tx) => tx.id)), [txs]);
  const visibleTransactionGroups = useMemo(
    () => transactionGroups.filter((group) =>
      group.transactions.some((tx) => loadedTransactionIds.has(tx.id))
    ),
    [transactionGroups, loadedTransactionIds]
  );
  const groupedTransactionIds = useMemo(
    () => new Set(visibleTransactionGroups.flatMap((group) => group.transactions.map((tx) => tx.id))),
    [visibleTransactionGroups]
  );
  const timelineItems = useMemo(() => {
    const items: Array<
      | { type: "transaction"; date: string; transaction: Transaction }
      | { type: "group"; date: string; group: TransactionGroup }
    > = [
      ...txs
        .filter((tx) => !groupedTransactionIds.has(tx.id))
        .map((transaction) => ({
          type: "transaction" as const,
          date: transaction.booking_date,
          transaction,
        })),
      ...visibleTransactionGroups
        .map((group) => ({
        type: "group" as const,
        date: group.transactions.reduce(
          (latest, tx) => (tx.booking_date > latest ? tx.booking_date : latest),
          group.transactions[0]?.booking_date || ""
        ),
        group,
      })),
    ];
    return items.sort((a, b) => b.date.localeCompare(a.date));
  }, [txs, visibleTransactionGroups, groupedTransactionIds]);

  const transactionParams = useCallback((offset: number) => {
    const params = new URLSearchParams({
      from: range.from,
      to: range.to,
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });
    if (search.trim()) params.set("q", search.trim());
    if (kind) params.set("kind", kind);
    if (accountId) params.set("account_id", accountId);
    if (categoryId) params.set("category_id", categoryId);
    return params;
  }, [accountId, categoryId, kind, range.from, range.to, search]);

  const load = useCallback(() => {
    const version = ++requestVersionRef.current;
    nextOffsetRef.current = 0;
    loadingMoreRef.current = false;
    setLoading(true);
    setLoadingMore(false);
    setHasMore(false);
    setTxs([]);
    const params = transactionParams(0);
    const tagParams = new URLSearchParams({ from_date: range.from, to_date: range.to });
    Promise.all([
      api.transactionPage(params),
      api.transactionGroups(params),
      api.accounts(),
      api.connections(),
      api.categories(),
      api.tags(),
      api.tagAssignments(tagParams),
    ])
      .then(([page, groups, loadedAccounts, loadedConnections, cats, loadedTags, assignments]) => {
        if (requestVersionRef.current !== version) return;
        setTxs(page.items);
        nextOffsetRef.current = page.next_offset ?? page.items.length;
        setHasMore(page.has_more);
        setTransactionGroups(groups);
        setAccounts(loadedAccounts);
        setConnections(loadedConnections);
        setCategories(cats);
        setTags(loadedTags);
        setTagAssignments(assignments);
        setError(null);
      })
      .catch((err: Error) => {
        if (requestVersionRef.current === version) setError(err.message);
      })
      .finally(() => {
        if (requestVersionRef.current === version) setLoading(false);
      });
  }, [range.from, range.to, transactionParams]);

  useEffect(() => {
    load();
  }, [load]);

  // Dashboard chart links carry human-readable category/account identifiers.
  // Resolve them after the encrypted lookup lists have loaded, then let the
  // normal query pipeline fetch the filtered result set.
  useEffect(() => {
    if (queryCategory && !categoryQueryAppliedRef.current && categories.length > 0) {
      const needle = queryCategory.toLocaleLowerCase();
      const match = categories.find((category) =>
        category.slug.toLocaleLowerCase() === needle
        || category.name.toLocaleLowerCase() === needle
      );
      if (match) setCategoryId(String(match.id));
      categoryQueryAppliedRef.current = true;
    }
  }, [categories, queryCategory]);

  useEffect(() => {
    if (queryAccount && !accountQueryAppliedRef.current && accounts.length > 0) {
      const needle = queryAccount.toLocaleLowerCase();
      const match = accounts.find((account) =>
        String(account.id) === queryAccount
        || account.name.toLocaleLowerCase() === needle
      );
      if (match) setAccountId(String(match.id));
      accountQueryAppliedRef.current = true;
    }
  }, [accounts, queryAccount]);

  // Categorization runs in a separate background loop. Refresh the visible
  // page when that loop has applied new decisions so categories do not appear
  // to be missing until the user manually reloads the page.
  useEffect(() => {
    const applied = assistant?.llm_applied_session;
    if (applied == null) return;
    const active = Boolean(
      assistant
      && (
        assistant.phase === "running"
        || assistant.phase === "researching"
        || assistant.phase === "waiting_ollama"
        || assistant.queue_remaining > 0
      )
    );
    const appliedChanged =
      lastAppliedCategorizationRef.current != null
      && applied !== lastAppliedCategorizationRef.current;
    const completed = wasCategorizingRef.current && !active;
    if (active) wasCategorizingRef.current = true;
    else wasCategorizingRef.current = false;
    lastAppliedCategorizationRef.current = applied;

    // The LLM loop is separate from the sync job. Reload once after it has
    // finished (or when a very fast run was only observed in the idle state),
    // so newly assigned categories become visible without manual refresh.
    if (completed || (appliedChanged && !active)) {
      if (categorizationRefreshTimerRef.current !== undefined) {
        window.clearTimeout(categorizationRefreshTimerRef.current);
      }
      categorizationRefreshTimerRef.current = window.setTimeout(() => {
        categorizationRefreshTimerRef.current = undefined;
        load();
      }, 150);
    }
    return () => {
      if (categorizationRefreshTimerRef.current !== undefined) {
        window.clearTimeout(categorizationRefreshTimerRef.current);
        categorizationRefreshTimerRef.current = undefined;
      }
    };
  }, [assistant?.llm_applied_session, assistant?.phase, assistant?.queue_remaining, load]);

  const loadMore = useCallback(async () => {
    if (loadingMoreRef.current || !hasMore) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    const version = requestVersionRef.current;
    try {
      const page = await api.transactionPage(transactionParams(nextOffsetRef.current));
      if (requestVersionRef.current !== version) return;
      setTxs((current) => {
        const known = new Set(current.map((tx) => tx.id));
        return [...current, ...page.items.filter((tx) => !known.has(tx.id))];
      });
      nextOffsetRef.current = page.next_offset ?? nextOffsetRef.current + page.items.length;
      setHasMore(page.has_more);
      setError(null);
    } catch (err) {
      if (requestVersionRef.current === version) {
        setError(err instanceof Error ? err.message : t("transactions.loadFailed"));
      }
    } finally {
      loadingMoreRef.current = false;
      if (requestVersionRef.current === version) setLoadingMore(false);
    }
  }, [hasMore, t, transactionParams]);

  useEffect(() => {
    const target = loadMoreRef.current;
    if (!target || !hasMore || loading) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMore();
      },
      { rootMargin: "500px 0px" }
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMore, loadMore, loading, timelineItems.length]);

  const onCategoryChange = async (txId: number, categoryId: string) => {
    try {
      const updated = await api.updateTransaction(txId, {
        category_id: categoryId ? Number(categoryId) : null,
      });
      setTxs((current) => current.map((tx) => (tx.id === txId ? updated : tx)));
      setTransactionGroups((current) => current.map((group) => ({
        ...group,
        transactions: group.transactions.map((tx) =>
          tx.id === txId ? { ...tx, ...updated } : tx
        ),
      })));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("transactions.updateFailed"));
    }
  };

  const addTag = async (txId: number, tagId: number) => {
    try {
      const assignment = await api.assignTag(txId, tagId);
      setTagAssignments((current) =>
        current.some((item) => item.id === assignment.id) ? current : [...current, assignment]
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t("tags.assignFailed"));
    }
  };

  const removeTag = async (txId: number, tagId: number) => {
    try {
      await api.unassignTag(txId, tagId);
      setTagAssignments((current) =>
        current.filter((item) => !(item.transaction_id === txId && item.tag_id === tagId))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t("tags.removeFailed"));
    }
  };

  const kindLabel = (value: string) => {
    const key = `kinds.${value}` as const;
    return t(key, { defaultValue: value });
  };

  const reviewGroup = async (groupId: number, decision: "confirm" | "reject") => {
    setReviewingLinkId(groupId);
    setError(null);
    try {
      if (decision === "confirm") {
        await api.confirmTransactionGroup(groupId);
      } else {
        await api.rejectTransactionGroup(groupId);
      }
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("transactions.updateFailed"));
    } finally {
      setReviewingLinkId(null);
    }
  };

  const renderGroupCard = (group: TransactionGroup) => (
    <TransactionGroupCard
      group={group}
      categories={categories}
      tags={tags}
      tagsByTransaction={tagsByTransaction}
      language={i18n.language}
      categoryLabel={t("transactions.category")}
      explanationLabel={t("transactions.aiExplanationLabel")}
      uncategorizedLabel={t("transactions.uncategorized")}
      addTagLabel={t("tags.add")}
      transferLabel={t("transactions.transferGroup")}
      brokerFundingLabel={t("transactions.brokerFundingGroup")}
      fundingLabel={t("transactions.fundingGroup")}
      suggestionLabel={t("transactions.matchSuggestion")}
      confirmLabel={t("transactions.confirmMatch")}
      rejectLabel={t("transactions.rejectMatch")}
      unlinkLabel={t("transactions.unlinkMatch")}
      reviewing={reviewingLinkId === group.id}
      onCategoryChange={(txId, categoryId) => void onCategoryChange(txId, categoryId)}
      onAddTag={(txId, tagId) => void addTag(txId, tagId)}
      onRemoveTag={(txId, tagId) => void removeTag(txId, tagId)}
      onConfirm={() => void reviewGroup(group.id, "confirm")}
      onReject={() => void reviewGroup(group.id, "reject")}
      onOpenTransaction={setSelectedTransaction}
    />
  );

  const selectedAccount = selectedTransaction
    ? accountMap[selectedTransaction.account_id]
    : undefined;
  const selectedCategory = selectedTransaction?.category_id
    ? catMap[selectedTransaction.category_id]
    : undefined;
  const selectedTags = selectedTransaction
    ? tagsByTransaction[selectedTransaction.id] || []
    : [];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">{t("transactions.title")}</h2>
          {categorizing && assistant && (
            <div className="mt-2 inline-flex max-w-full items-center gap-2 rounded-full bg-warning/12 px-2.5 py-1 text-xs font-medium text-warning">
              <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-current" />
              <span className="truncate">
                {assistant.phase === "researching"
                  ? t("transactions.categorizationResearching", {
                      current: categorizationCurrent,
                      total: categorizationTotal,
                      merchant: assistant.current?.counterparty || t("common.emDash"),
                    })
                  : assistant.phase === "waiting_ollama"
                  ? t("transactions.categorizationWaiting", {
                      current: categorizationCurrent,
                      total: categorizationTotal,
                    })
                  : t("transactions.categorizationProgress", {
                      current: categorizationCurrent,
                      total: categorizationTotal,
                      merchant: assistant.current?.counterparty || t("common.emDash"),
                    })}
              </span>
            </div>
          )}
      </div>
      <Card className="space-y-3 p-3">
        <div className="flex items-center gap-2">
          <div className="relative min-w-0 flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden /><Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("transactions.searchPlaceholder")} className="pl-9 pr-3" /></div>
          <Button variant="outline" className="h-10 w-10 shrink-0 rounded-xl p-0" onClick={() => setFiltersOpen((value) => !value)} aria-label={t("transactions.showFilters")} aria-expanded={filtersOpen}><SlidersHorizontal className="h-4 w-4" aria-hidden /></Button>
        </div>
        {filtersOpen && <div className="grid grid-cols-2 gap-2 border-t border-border/35 pt-3 sm:flex sm:flex-wrap">
          <Select className="w-full" value={year} onChange={(e) => { setUrlRange(null); setYear(Number(e.target.value)); }}>
            {[year - 2, year - 1, year].map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </Select>
          <Select className="w-full" value={month} onChange={(e) => { setUrlRange(null); setMonth(Number(e.target.value)); }}>
            <option value={0}>{t("transactions.allMonths")}</option>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
              <option key={m} value={m}>
                {m.toString().padStart(2, "0")}
              </option>
            ))}
          </Select>
          <Select className="w-full sm:w-auto" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">{t("kinds.all")}</option>
            <option value="expense">{t("kinds.expense")}</option>
            <option value="income">{t("kinds.income")}</option>
            <option value="transfer">{t("kinds.transfer")}</option>
            <option value="ignore">{t("kinds.ignore")}</option>
          </Select>
          <Select
            className="w-full sm:max-w-52"
            value={categoryId}
            aria-label={t("transactions.category")}
            onChange={(event) => setCategoryId(event.target.value)}
          >
            <option value="">{t("transactions.allCategories")}</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>{category.name}</option>
            ))}
          </Select>
          <Select
            className="col-span-2 w-full sm:max-w-56"
            value={accountId}
            aria-label={t("transactions.account")}
            onChange={(event) => setAccountId(event.target.value)}
          >
            <option value="">{t("transactions.allAccounts")}</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>{account.name}</option>
            ))}
          </Select>
        </div>}
      </Card>

      {error && <p className="text-sm text-danger">{error}</p>}

      {loading && (
        <Card className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t("common.loading")}
        </Card>
      )}

      {!loading && timelineItems.length > 0 && isDesktop && (
        <Card className="overflow-x-auto p-0">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-border bg-muted/60 text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">{t("transactions.date")}</th>
                <th className="px-4 py-3 font-medium">{t("transactions.description")}</th>
                <th className="px-4 py-3 font-medium">{t("transactions.category")}</th>
                <th className="px-4 py-3 font-medium text-right">{t("transactions.amount")}</th>
              </tr>
            </thead>
            <tbody>
              {timelineItems.map((item) => {
                if (item.type === "group") {
                  return (
                    <tr key={`group-${item.group.id}`} className="border-b border-border/70 last:border-0">
                      <td colSpan={4} className="bg-muted/15 p-3">
                        {renderGroupCard(item.group)}
                      </td>
                    </tr>
                  );
                }
                const tx = item.transaction;
                const account = accountMap[tx.account_id];
                return (
                  <tr
                    key={tx.id}
                    className="cursor-pointer border-b border-border/70 outline-none transition hover:bg-muted/20 focus-visible:bg-muted/25 last:border-0"
                    role="button"
                    tabIndex={0}
                    onClick={(event: MouseEvent) => {
                      if (!eventTargetsControl(event.target)) setSelectedTransaction(tx);
                    }}
                    onKeyDown={(event) => openFromKeyboard(event, () => setSelectedTransaction(tx))}
                  >
                    <td className="px-4 py-3 whitespace-nowrap">{tx.booking_date}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-start gap-2.5">
                        <span
                          className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-muted/60 text-muted-foreground"
                          title={account?.name}
                        >
                          <AccountIcon
                            source={account?.source}
                            provider={
                              account?.connection_id
                                ? connectionMap[account.connection_id]?.provider
                                : undefined
                            }
                            bankBrand={
                              account?.connection_id
                                ? connectionMap[account.connection_id]?.public_fields.bank_brand
                                : undefined
                            }
                            bankName={
                              account?.connection_id
                                ? connectionMap[account.connection_id]?.public_fields.bank_name
                                  || connectionMap[account.connection_id]?.name
                                : undefined
                            }
                            bic={
                              account?.connection_id
                                ? connectionMap[account.connection_id]?.public_fields.bank_bic
                                : undefined
                            }
                            accountType={account?.account_type}
                            className="h-3.5 w-3.5"
                          />
                        </span>
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5 font-medium">
                            <span className="min-w-0 truncate">
                              <HighlightText value={tx.counterparty || t("common.emDash")} query={search} />
                            </span>
                            <TransactionExplanationButton
                              transaction={tx}
                              label={t("transactions.aiExplanationLabel")}
                              onOpen={() => setSelectedTransaction(tx)}
                            />
                          </div>
                          <div className="max-w-md truncate text-muted-foreground"><HighlightText value={tx.raw_text} query={search} /></div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <CategoryPicker
                        value={tx.category_id}
                        categories={categories}
                        emptyLabel={t("transactions.uncategorized")}
                        ariaLabel={t("transactions.category")}
                        onChange={(value) => onCategoryChange(tx.id, value)}
                      />
                      <div className="mt-2">
                        <TransactionTags
                          tags={tags}
                          assigned={tagsByTransaction[tx.id] || []}
                          addLabel={t("tags.add")}
                          onAdd={(tagId) => void addTag(tx.id, tagId)}
                          onRemove={(tagId) => void removeTag(tx.id, tagId)}
                        />
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right font-medium" style={{ color: transactionAmountColor(tx.kind) }}>
                      {formatMoney(tx.amount, tx.currency, i18n.language)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {!loading && !isDesktop && <div className="space-y-3">
        {timelineItems.map((item) => {
          if (item.type === "group") {
            return <div key={`group-${item.group.id}`}>{renderGroupCard(item.group)}</div>;
          }
          const tx = item.transaction;
          const account = accountMap[tx.account_id];
          return (
            <div
              key={tx.id}
              role="button"
              tabIndex={0}
              className="rounded-[1.65rem] outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              onClick={(event) => {
                if (!eventTargetsControl(event.target)) setSelectedTransaction(tx);
              }}
              onKeyDown={(event) => openFromKeyboard(event, () => setSelectedTransaction(tx))}
            >
            <Card className="cursor-pointer space-y-4 p-4 transition hover:bg-card/25">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-2.5">
                  <span
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-muted/60 text-muted-foreground"
                    title={account?.name}
                  >
                    <AccountIcon
                      source={account?.source}
                      provider={
                        account?.connection_id
                          ? connectionMap[account.connection_id]?.provider
                          : undefined
                      }
                      bankBrand={
                        account?.connection_id
                          ? connectionMap[account.connection_id]?.public_fields.bank_brand
                          : undefined
                      }
                      bankName={
                        account?.connection_id
                          ? connectionMap[account.connection_id]?.public_fields.bank_name
                            || connectionMap[account.connection_id]?.name
                          : undefined
                      }
                      bic={
                        account?.connection_id
                          ? connectionMap[account.connection_id]?.public_fields.bank_bic
                          : undefined
                      }
                      accountType={account?.account_type}
                    />
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-start gap-1.5">
                      <p className="min-w-0 break-words font-medium">
                        <HighlightText value={tx.counterparty || t("common.emDash")} query={search} />
                      </p>
                      <TransactionExplanationButton
                        transaction={tx}
                        label={t("transactions.aiExplanationLabel")}
                        onOpen={() => setSelectedTransaction(tx)}
                      />
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">{tx.booking_date}</p>
                  </div>
                </div>
                <p className="shrink-0 text-right font-semibold tabular-nums" style={{ color: transactionAmountColor(tx.kind) }}>
                  {formatMoney(tx.amount, tx.currency, i18n.language)}
                </p>
              </div>
              {tx.raw_text && (
                <p className="line-clamp-3 break-words text-sm text-muted-foreground">
                  {tx.raw_text}
                </p>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <CategoryPicker
                  value={tx.category_id}
                  categories={categories}
                  emptyLabel={t("transactions.uncategorized")}
                  ariaLabel={t("transactions.category")}
                  onChange={(value) => onCategoryChange(tx.id, value)}
                />
                <TransactionTags
                  tags={tags}
                  assigned={tagsByTransaction[tx.id] || []}
                  addLabel={t("tags.add")}
                  onAdd={(tagId) => void addTag(tx.id, tagId)}
                  onRemove={(tagId) => void removeTag(tx.id, tagId)}
                />
              </div>
            </Card>
            </div>
          );
        })}
      </div>}
      {!loading && timelineItems.length === 0 && (
        <Card className="py-8 text-center text-sm text-muted-foreground">
          {t("transactions.empty")}
        </Card>
      )}
      {!loading && timelineItems.length > 0 && (
        <div ref={loadMoreRef} className="flex min-h-16 flex-col items-center justify-center gap-2 py-2">
          {hasMore ? (
            <Button
              type="button"
              variant="ghost"
              className="gap-2 text-muted-foreground"
              disabled={loadingMore}
              onClick={() => void loadMore()}
            >
              {loadingMore && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
              {loadingMore ? t("transactions.loadingMore") : t("transactions.loadMore")}
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">
              {t("transactions.loadedCount", { count: txs.length })}
            </p>
          )}
        </div>
      )}

      {selectedTransaction && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-background/80 p-0 sm:items-center sm:bg-background/70 sm:p-4 sm:backdrop-blur-sm"
          onClick={() => setSelectedTransaction(null)}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="transaction-detail-title"
            className="modal-surface max-h-[92dvh] w-full max-w-xl overflow-y-auto rounded-[1.65rem_1.65rem_0_0] px-4 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-5 sm:max-h-[88vh] sm:rounded-[1.65rem] sm:p-6"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                  {t("transactions.details")}
                </p>
                <h3 id="transaction-detail-title" className="mt-1 break-words text-xl font-semibold">
                  {selectedTransaction.counterparty || t("common.emDash")}
                </h3>
              </div>
              <Button
                type="button"
                variant="ghost"
                className="h-9 w-9 shrink-0 rounded-full p-0"
                onClick={() => setSelectedTransaction(null)}
                aria-label={t("common.close")}
                autoFocus
              >
                <X className="h-4 w-4" aria-hidden />
              </Button>
            </div>

            <p
              className="mt-4 text-2xl font-semibold tabular-nums"
              style={{ color: transactionAmountColor(selectedTransaction.kind) }}
            >
              {formatMoney(selectedTransaction.amount, selectedTransaction.currency, i18n.language)}
            </p>

            {(selectedTransaction.categorized_by === "llm" || selectedTransaction.categorization_reason) && (
              <div className="mt-5 rounded-2xl border border-border/40 bg-muted/20 p-4">
                <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                  <Info className="h-4 w-4" aria-hidden />
                  <span>{t("transactions.aiExplanationTitle")}</span>
                </div>
                <p className="mt-2 text-sm leading-relaxed">
                  {selectedTransaction.categorization_reason || t("transactions.aiExplanationMissing")}
                </p>
              </div>
            )}

            <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4 rounded-2xl bg-muted/25 p-4 text-sm">
              <div>
                <dt className="text-xs text-muted-foreground">{t("transactions.date")}</dt>
                <dd className="mt-0.5 font-medium">{selectedTransaction.booking_date}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("transactions.account")}</dt>
                <dd className="mt-0.5 break-words font-medium">
                  {selectedAccount?.name || t("common.emDash")}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("transactions.kind")}</dt>
                <dd className="mt-0.5 font-medium">
                  <TransactionKindBadge kind={selectedTransaction.kind} label={kindLabel(selectedTransaction.kind)} />
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("transactions.category")}</dt>
                <dd className="mt-0.5 break-words font-medium">
                  {selectedCategory?.name || t("transactions.uncategorized")}
                </dd>
              </div>
            </dl>

            <div className="mt-5">
              <p className="text-xs font-medium text-muted-foreground">
                {t("transactions.bookingText")}
              </p>
              <p className="mt-2 whitespace-pre-wrap break-words rounded-2xl border border-border/40 bg-card/25 p-4 text-sm leading-relaxed">
                {selectedTransaction.raw_text || t("common.emDash")}
              </p>
            </div>

            {selectedTags.length > 0 && (
              <div className="mt-5">
                <p className="mb-2 text-xs font-medium text-muted-foreground">{t("tags.title")}</p>
                <div className="flex flex-wrap gap-1.5">
                  {selectedTags.map((tag) => (
                    <span
                      key={tag.id}
                      className="rounded-full px-2.5 py-1 text-xs font-medium text-slate-800"
                      style={{ backgroundColor: tag.color }}
                    >
                      {tag.name}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
