// Dev and production use the same-origin /api proxy unless VITE_API_URL is set.
// Prod (nginx): empty = same-origin /api proxy.
const API_URL =
  import.meta.env.VITE_API_URL ||
  "";

let authToken: string | null = null;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers,
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text || res.statusText;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      if (parsed.detail) detail = parsed.detail;
    } catch {
      /* keep text */
    }
    throw new Error(detail);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export type Account = {
  id: number;
  connection_id: number | null;
  source: string;
  external_id: string;
  name: string;
  currency: string;
  account_type: string;
  iban: string | null;
  is_active: boolean;
  current_balance: string | null;
  available_balance: string | null;
  balance_updated_at: string | null;
};

export type Transaction = {
  id: number;
  account_id: number;
  external_id: string;
  booking_date: string;
  amount: string;
  currency: string;
  raw_text: string;
  counterparty: string | null;
  kind: string;
  category_id: number | null;
  categorized_by: string | null;
  categorization_reason: string | null;
};

export type AssetPosition = {
  id: number;
  external_id: string;
  isin: string | null;
  name: string;
  asset_type: string | null;
  quantity: string;
  average_buy_in: string | null;
  current_price: string | null;
  market_value: string | null;
  cost_value: string | null;
  gain_value: string | null;
  gain_percent: string | null;
  performance_cost_value: string | null;
  currency: string;
};

export type Portfolio = {
  id: number;
  connection_id: number | null;
  source: string;
  name: string;
  currency: string;
  last_synced_at: string | null;
  total_market_value: string;
  total_cost_value: string;
  total_gain_value: string;
  total_gain_percent: string | null;
  performance_cost_value: string;
  priced_positions: number;
  positions: AssetPosition[];
};

export type AssetsOverview = { portfolios: Portfolio[] };
export type InflationSeries = {
  country: "DE";
  currency: "EUR";
  source: string;
  points: { month: string; index: string }[];
};

export type AssetHistory = {
  kind: "aggregate" | "portfolio" | "instrument";
  label: string;
  currency: string;
  estimated: boolean;
  source: "provider" | "calculated" | "hybrid_calibrated" | "mixed" | "market_price" | "unavailable";
  calibration: {
    offset: string;
    mean_absolute_error: string;
    max_absolute_error: string;
    overlap_points: number;
    matched: boolean;
  } | null;
  points: {
    timestamp: string;
    value: string;
    invested_value: string | null;
    performance_percent?: string | null;
  }[];
};

export type TransactionPage = {
  items: Transaction[];
  has_more: boolean;
  next_offset: number | null;
};

export type GroupedTransaction = Transaction & {
  account_name: string;
  account_source: string;
  account_provider: string | null;
  account_type: string;
};

export type TransactionGroup = {
  id: number;
  link_type: "internal_transfer" | "account_funding" | "broker_funding";
  status: "confirmed" | "suggested";
  confidence: string;
  reason: string | null;
  transactions: GroupedTransaction[];
};

export type Category = {
  id: number;
  name: string;
  slug: string;
  color: string;
  color_key: CategoryColorKey;
  icon: CategoryIconKey;
  description: string;
  is_system: boolean;
};

export type CategoryColorKey =
  | "housing" | "groceries" | "dining" | "mobility" | "health"
  | "subscriptions" | "shopping" | "leisure" | "travel" | "family"
  | "education" | "savings" | "finance" | "income" | "other";
export type CategoryIconKey =
  | "house" | "basket" | "utensils" | "car" | "heart" | "repeat"
  | "bag" | "culture" | "plane" | "users" | "education" | "savings"
  | "finance" | "income" | "other";
export type CategoryImpact = {
  assigned: number;
  automatic: number;
  manual: number;
  uncategorized: number;
};
export type CategoryMutation = {
  category: Category | null;
  reset_count: number;
  rules_applied: number;
  queued_for_agent: number;
};

export type CategoryRule = {
  id: number;
  category_id: number;
  pattern: string;
  is_regex: boolean;
  priority: number;
  is_active: boolean;
};

export type Tag = {
  id: number;
  name: string;
  tag_type: "general" | "trip" | "project";
  color: string;
  from_date: string | null;
  to_date: string | null;
  created_by: string;
};

export type TransactionTag = {
  id: number;
  transaction_id: number;
  tag_id: number;
  assigned_by: string;
  confidence: string;
  reason: string | null;
};

export type StatsSummary = {
  from_date: string;
  to_date: string;
  income: string;
  expense: string;
  spending: string;
  savings: string;
  net: string;
  transaction_count: number;
  by_category: {
    category_id: number | null;
    category_name: string;
    category_slug: string | null;
    color: string | null;
    color_key: string | null;
    icon: string | null;
    amount: string;
    count: number;
  }[];
  income_by_category: {
    category_id: number | null;
    category_name: string;
    category_slug: string | null;
    color: string | null;
    color_key: string | null;
    icon: string | null;
    amount: string;
    count: number;
  }[];
};

export type TimeseriesResponse = {
  grain: string;
  group_by: string;
  from_date: string;
  to_date: string;
  buckets: {
    period: string;
    income_total: string;
    expense_total: string;
    income_segments: { key: string; amount: string; category_slug: string | null; color: string | null; color_key: string | null; icon: string | null }[];
    expense_segments: { key: string; amount: string; category_slug: string | null; color: string | null; color_key: string | null; icon: string | null }[];
  }[];
};

export type FlowResponse = {
  from_date: string;
  to_date: string;
  group_by: string;
  nodes: {
    name: string;
    role: "hub" | "income" | "expense" | "saving";
    category_slug: string | null;
    color?: string | null;
    color_key?: string | null;
    icon?: string | null;
    group_by?: string | null;
    group_key?: string | null;
    account_source?: string | null;
    account_provider?: string | null;
  }[];
  links: { source: number; target: number; value: number }[];
};

export type EmbeddingPoint = { id: number; x: number; y: number; kind: "income" | "expense" | "other"; cluster?: number };
export type EmbeddingPointCloud = { points: EmbeddingPoint[]; clusters?: number[] };

export type SyncProgress = {
  phase: string;
  message: string | null;
  awaiting_user_action: boolean;
  source: string | null;
};

export type SyncStatus = {
  account_id: number;
  account_name: string;
  status: string;
  last_success_at: string | null;
  last_error: string | null;
  pending_jobs: number;
  latest_job_status: string | null;
  history_from: string | null;
  backfill_cursor: string | null;
  latest_booking_date: string | null;
  earliest_booking_date: string | null;
};

export type ConnectionSyncStatus = {
  connection_id: number;
  pending_jobs: number;
  running_jobs: number;
  latest_job_status: string | null;
  latest_job_error: string | null;
};

export type VaultStatus = {
  initialized: boolean;
  unlocked: boolean;
  recovery_configured: boolean;
  recovery_confirmed: boolean;
};

export type VaultSetupResult = {
  token: string;
  message: string;
  recovery_phrase: string;
};

export type Connection = {
  id: number;
  source: "volksbank" | "trade_republic" | "binance" | "trading_212" | "coinbase";
  provider: string;
  name: string;
  created_at: string;
  updated_at: string;
  last_error: string | null;
  public_fields: Record<string, string>;
};

export type BankDirectoryEntry = {
  blz: string;
  bic: string | null;
  name: string;
  location: string | null;
  pinTanAddress: string | null;
  pinTanVersion: string | null;
};

export type BankDirectoryResult = {
  items: BankDirectoryEntry[];
  count: number;
};

export type CategorizeStatus = {
  ollama_configured: boolean;
  ollama_reachable: boolean;
  phase: "idle" | "running" | "researching" | "waiting_ollama" | string;
  queue_remaining: number;
  queue_total: number;
  queue_processed: number;
  current: {
    id: number;
    booking_date: string;
    counterparty: string | null;
    amount: string;
  } | null;
  last_done: { id: number; slug: string; confidence: number }[];
  llm_applied_session: number;
  message: string | null;
};
export type OllamaAutoInstall = {
  enabled: boolean;
  phase: "disabled" | "pending" | "waiting" | "checking" | "downloading" | "ready" | "error";
  model: string | null;
  completed: number;
  total: number;
  error: string | null;
};
export type OllamaModels = {
  reachable: boolean;
  active: string;
  models: string[];
  embedding_active: string;
  embedding_models: string[];
  auto_install: OllamaAutoInstall;
};
export type LlmPreferences = {
  categorization_web_search_enabled: boolean;
};
export type OnboardingStatus = {
  completed: boolean;
};
export type OllamaModelKind = "chat" | "embedding";
export type OllamaPullProgress = {
  status?: string;
  digest?: string;
  total?: number;
  completed?: number;
  model?: string;
  kind?: OllamaModelKind;
  error?: string;
};

export type AgentMessage = {
  role: "user" | "assistant" | "summary";
  content: string;
};

export type AgentChatResponse = {
  conversation_id: number;
  user_message_id: number;
  assistant_message_id: number;
  message: AgentMessage;
  context: AgentMessage[];
};

export type AgentConversationSummary = {
  id: number;
  title: string;
  preview: string;
  message_count: number;
  created_at: string;
  updated_at: string;
};

export type AgentConversationDetail = AgentConversationSummary & {
  messages: Array<{
    id: number;
    role: "user" | "assistant";
    content: string;
    created_at: string;
  }>;
};

export type AgentStreamEvent =
  | { type: "answer_reset" }
  | { type: "token"; content: string }
  | {
      type: "activity";
      code: string;
      count?: number;
      offset?: number;
      has_more?: boolean;
    };

async function streamAgentChat(
  body: Record<string, unknown>,
  onEvent: (event: AgentStreamEvent) => void
): Promise<AgentChatResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  const response = await fetch(`${API_URL}/api/agent/chat/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    let detail = text || response.statusText;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      if (parsed.detail) detail = parsed.detail;
    } catch {
      /* keep text */
    }
    throw new Error(detail);
  }
  if (!response.body) throw new Error("Streaming response has no body");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed: AgentChatResponse | null = null;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as
        | AgentStreamEvent
        | { type: "complete"; response: AgentChatResponse }
        | { type: "error"; detail: string };
      if (event.type === "error") throw new Error(event.detail);
      if (event.type === "complete") completed = event.response;
      else onEvent(event);
    }
    if (done) break;
  }
  if (!completed) throw new Error("Agent stream ended without a final response");
  return completed;
}

export const api = {
  setAuthToken: (token: string | null) => {
    authToken = token;
  },
  health: () => request<{ status: string }>("/api/health"),
  vaultStatus: () => request<VaultStatus>("/api/vault/status"),
  vaultSetup: (password: string) =>
    request<VaultSetupResult>("/api/vault/setup", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  vaultUnlock: (password: string) =>
    request<{ token: string; message: string }>("/api/vault/unlock", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  vaultRecover: (recoveryPhrase: string, newPassword: string) =>
    request<{ token: string; message: string }>("/api/vault/recover", {
      method: "POST",
      body: JSON.stringify({
        recovery_phrase: recoveryPhrase,
        new_password: newPassword,
      }),
    }),
  vaultConfirmRecovery: (recoveryPhrase: string, token?: string, replace = false) =>
    request<VaultStatus>("/api/vault/recovery/confirm", {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      body: JSON.stringify({ recovery_phrase: recoveryPhrase, replace }),
    }),
  vaultRegenerateRecovery: () =>
    request<{ recovery_phrase: string }>("/api/vault/recovery/regenerate", {
      method: "POST",
    }),
  vaultLock: () => request<VaultStatus>("/api/vault/lock", { method: "POST" }),
  connections: () => request<Connection[]>("/api/connections"),
  searchBanks: (query: string, limit = 20) =>
    request<BankDirectoryResult>(
      `/api/banks?query=${encodeURIComponent(query)}&limit=${limit}`
    ),
  createConnection: (body: {
    source: string;
    provider?: string;
    name: string;
    secrets: Record<string, string>;
  }) =>
    request<Connection>("/api/connections", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateConnection: (
    id: number,
    body: {
      name?: string;
      secrets?: Record<string, string>;
    }
  ) =>
    request<Connection>(`/api/connections/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteConnection: (id: number) =>
    request<void>(`/api/connections/${id}`, { method: "DELETE" }),
  deleteAccount: (id: number) =>
    request<void>(`/api/accounts/${id}`, { method: "DELETE" }),
  accounts: () => request<Account[]>("/api/accounts"),
  assets: () => request<AssetsOverview>("/api/assets"),
  embeddingPointCloud: (limit = 2000) => request<EmbeddingPointCloud>(`/api/embeddings/point-cloud?limit=${limit}`),
  backfillEmbeddings: (limit = 500) => request<{ candidates: number; embedded: number }>(`/api/embeddings/backfill?limit=${limit}`, { method: "POST" }),
  assetHistory: (params: URLSearchParams) =>
    request<AssetHistory>(`/api/assets/history?${params}`),
  germanyInflation: () => request<InflationSeries>("/api/inflation/germany"),
  ollamaModels: () => request<OllamaModels>("/api/llm/models"),
  llmPreferences: () => request<LlmPreferences>("/api/llm/preferences"),
  onboardingStatus: () => request<OnboardingStatus>("/api/onboarding"),
  setOnboardingCompleted: (completed: boolean) =>
    request<OnboardingStatus>("/api/onboarding", {
      method: "PUT",
      body: JSON.stringify({ completed }),
    }),
  setCategorizationWebSearch: (enabled: boolean) =>
    request<LlmPreferences>("/api/llm/preferences/categorization-web-search", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  configureInitialOllamaModels: (model: string) =>
    request<{ model: string; status: string }>("/api/llm/models/setup", {
      method: "POST",
      body: JSON.stringify({ model }),
    }),
  pullOllamaModel: async (
    model: string,
    kind: OllamaModelKind,
    onProgress: (event: OllamaPullProgress) => void,
  ) => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (authToken) headers.Authorization = `Bearer ${authToken}`;
    const response = await fetch(`${API_URL}/api/llm/models/pull`, {
      method: "POST",
      headers,
      body: JSON.stringify({ model, kind }),
    });
    if (!response.ok) {
      const text = await response.text();
      let detail = text || response.statusText;
      try {
        detail = (JSON.parse(text) as { detail?: string }).detail || detail;
      } catch {
        // Keep the response text when the server did not return JSON.
      }
      throw new Error(detail);
    }
    if (!response.body) throw new Error("Ollama returned no progress stream");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line) as OllamaPullProgress;
        if (event.error) throw new Error(event.error);
        onProgress(event);
      }
      if (done) break;
    }
    if (buffer.trim()) {
      const event = JSON.parse(buffer) as OllamaPullProgress;
      if (event.error) throw new Error(event.error);
      onProgress(event);
    }
  },
  selectOllamaModel: (model: string) => request<{
    active: string;
    changed: boolean;
    reset_count: number;
    rules_applied: number;
    queued_for_agent: number;
  }>("/api/llm/model", {
    method: "POST",
    body: JSON.stringify({ model }),
  }),
  selectOllamaEmbeddingModel: (model: string) => request<{
    active: string;
    changed: boolean;
    rebuild_started: boolean;
  }>("/api/llm/embedding-model", {
    method: "POST",
    body: JSON.stringify({ model }),
  }),
  updateAccount: (id: number, body: { name?: string }) =>
    request<Account>(`/api/accounts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  transactions: (params: URLSearchParams) =>
    request<Transaction[]>(`/api/transactions?${params}`),
  transactionPage: (params: URLSearchParams) =>
    request<TransactionPage>(`/api/transactions/page?${params}`),
  recategorize: (body: {
    account_id?: number | null;
    category_id?: number | null;
    include_manual?: boolean;
  } = {}) => request<{
    reset_count: number;
    rules_applied: number;
    queued_for_agent: number;
  }>("/api/categorize/reprocess", {
    method: "POST",
    body: JSON.stringify(body),
  }),
  transactionGroups: (params: URLSearchParams) =>
    request<TransactionGroup[]>(`/api/transactions/groups?${params}`),
  confirmTransactionGroup: (id: number) =>
    request<void>(`/api/transactions/groups/${id}/confirm`, { method: "POST" }),
  rejectTransactionGroup: (id: number) =>
    request<void>(`/api/transactions/groups/${id}/reject`, { method: "POST" }),
  updateTransaction: (id: number, body: { category_id?: number | null; kind?: string }) =>
    request<Transaction>(`/api/transactions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  categories: () => request<Category[]>("/api/categories"),
  categoryImpact: (id?: number) => request<CategoryImpact>(
    id === undefined ? "/api/categories/impact" : `/api/categories/${id}/impact`
  ),
  createCategory: (body: {
    name: string;
    description: string;
    color_key: CategoryColorKey;
    icon: CategoryIconKey;
  }) => request<CategoryMutation>("/api/categories", {
    method: "POST",
    body: JSON.stringify(body),
  }),
  updateCategory: (id: number, body: Partial<{
    name: string;
    description: string;
    color_key: CategoryColorKey;
    icon: CategoryIconKey;
  }>) => request<CategoryMutation>(`/api/categories/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  }),
  deleteCategory: (id: number) => request<CategoryMutation>(`/api/categories/${id}`, {
    method: "DELETE",
  }),
  tags: () => request<Tag[]>("/api/tags"),
  createTag: (body: {
    name: string;
    tag_type?: "general" | "trip" | "project";
    color?: string;
    from_date?: string | null;
    to_date?: string | null;
  }) => request<Tag>("/api/tags", { method: "POST", body: JSON.stringify(body) }),
  updateTag: (id: number, body: Partial<Pick<Tag, "name" | "tag_type" | "color" | "from_date" | "to_date">>) =>
    request<Tag>(`/api/tags/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteTag: (id: number) => request<void>(`/api/tags/${id}`, { method: "DELETE" }),
  tagAssignments: (params?: URLSearchParams) =>
    request<TransactionTag[]>(`/api/tag-assignments${params ? `?${params}` : ""}`),
  assignTag: (transactionId: number, tagId: number) =>
    request<TransactionTag>(`/api/transactions/${transactionId}/tags/${tagId}`, { method: "POST" }),
  unassignTag: (transactionId: number, tagId: number) =>
    request<void>(`/api/transactions/${transactionId}/tags/${tagId}`, { method: "DELETE" }),
  categoryRules: () => request<CategoryRule[]>("/api/category-rules"),
  createCategoryRule: (body: {
    category_id: number;
    pattern: string;
    is_regex?: boolean;
    priority?: number;
  }) =>
    request<CategoryRule>("/api/category-rules", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  stats: (params: URLSearchParams) =>
    request<StatsSummary>(`/api/stats/summary?${params}`),
  statsTimeseries: (params: URLSearchParams) =>
    request<TimeseriesResponse>(`/api/stats/timeseries?${params}`),
  statsFlow: (params: URLSearchParams) =>
    request<FlowResponse>(`/api/stats/flow?${params}`),
  triggerSync: (body?: {
    account_id?: number;
    connection_id?: number;
    source?: string;
    mode?: "sync" | "backfill";
    history_from?: string;
  }) =>
    request<{ job_ids: number[]; message: string }>("/api/sync", {
      method: "POST",
      body: JSON.stringify(body || {}),
    }),
  updateSyncSettings: (accountId: number, body: { history_from?: string | null }) =>
    request<SyncStatus>(`/api/sync/accounts/${accountId}/settings`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  syncStatus: () => request<SyncStatus[]>("/api/sync/status"),
  connectionSyncStatus: () =>
    request<ConnectionSyncStatus[]>("/api/sync/connections/status"),
  syncProgress: () => request<SyncProgress>("/api/sync/progress"),
  categorizeStatus: () => request<CategorizeStatus>("/api/categorize/status"),
  agentChat: (
    messages: AgentMessage[],
    conversationId?: number | null,
    replaceMessageId?: number | null,
    webSearchEnabled = true,
  ) =>
    request<AgentChatResponse>("/api/agent/chat", {
      method: "POST",
      body: JSON.stringify({
        messages,
        conversation_id: conversationId ?? null,
        replace_message_id: replaceMessageId ?? null,
        local_date: (() => {
          const now = new Date();
          const year = now.getFullYear();
          const month = String(now.getMonth() + 1).padStart(2, "0");
          const day = String(now.getDate()).padStart(2, "0");
          return `${year}-${month}-${day}`;
        })(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        web_search_enabled: webSearchEnabled,
      }),
    }),
  agentChatStream: (
    messages: AgentMessage[],
    conversationId: number | null | undefined,
    replaceMessageId: number | null | undefined,
    onEvent: (event: AgentStreamEvent) => void,
    webSearchEnabled = true,
  ) => {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return streamAgentChat(
      {
        messages,
        conversation_id: conversationId ?? null,
        replace_message_id: replaceMessageId ?? null,
        local_date: `${year}-${month}-${day}`,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        web_search_enabled: webSearchEnabled,
      },
      onEvent
    );
  },
  agentConversations: () =>
    request<AgentConversationSummary[]>("/api/agent/conversations"),
  agentConversation: (id: number) =>
    request<AgentConversationDetail>(`/api/agent/conversations/${id}`),
  deleteAgentConversation: (id: number) =>
    request<void>(`/api/agent/conversations/${id}`, { method: "DELETE" }),
};
