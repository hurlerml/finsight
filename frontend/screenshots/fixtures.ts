import type { Page, Route } from "@playwright/test";

const categories = [
  { id: 1, name: "Housing", slug: "housing", color: "#8b9cf5", color_key: "housing", icon: "house", description: "Rent and household costs", is_system: true },
  { id: 2, name: "Groceries", slug: "groceries", color: "#42c4a3", color_key: "groceries", icon: "basket", description: "Food and everyday essentials", is_system: true },
  { id: 3, name: "Dining", slug: "dining", color: "#f2aa67", color_key: "dining", icon: "utensils", description: "Restaurants and cafés", is_system: true },
  { id: 4, name: "Mobility", slug: "mobility", color: "#68a4ee", color_key: "mobility", icon: "car", description: "Public transport and mobility", is_system: true },
  { id: 5, name: "Leisure", slug: "leisure", color: "#c78af2", color_key: "leisure", icon: "culture", description: "Culture and recreation", is_system: true },
  { id: 6, name: "Subscriptions", slug: "subscriptions", color: "#ec7595", color_key: "subscriptions", icon: "repeat", description: "Recurring services", is_system: true },
  { id: 7, name: "Savings & investments", slug: "savings", color: "#75ca70", color_key: "savings", icon: "savings", description: "Long-term wealth building", is_system: true },
  { id: 8, name: "Income", slug: "income", color: "#4bcf91", color_key: "income", icon: "income", description: "Salary and other income", is_system: true },
];

const accounts = [
  {
    id: 1, connection_id: 1, source: "volksbank", external_id: "demo-current",
    name: "Everyday account", currency: "EUR", account_type: "checking",
    iban: "DE00 0000 0000 0000 0000 01", is_active: true,
    current_balance: "12480.35", available_balance: "12480.35",
    balance_updated_at: "2026-09-30T08:45:00Z",
  },
  {
    id: 2, connection_id: 2, source: "volksbank", external_id: "demo-savings",
    name: "Household account", currency: "EUR", account_type: "checking",
    iban: "DE00 0000 0000 0000 0000 02", is_active: true,
    current_balance: "7600.00", available_balance: "7600.00",
    balance_updated_at: "2026-09-30T08:42:00Z",
  },
  {
    id: 3, connection_id: 3, source: "trade_republic", external_id: "demo-broker-cash",
    name: "Broker cash", currency: "EUR", account_type: "broker_cash",
    iban: null, is_active: true, current_balance: "1825.20", available_balance: "1825.20",
    balance_updated_at: "2026-09-30T08:40:00Z",
  },
];

const connections = [
  { id: 1, source: "volksbank", provider: "generic_fints", name: "Main bank", created_at: "2026-01-03T10:00:00Z", updated_at: "2026-09-30T08:45:00Z", last_error: null, public_fields: { bank_brand: "sparkasse", bank_name: "Demo Sparkasse" } },
  { id: 2, source: "volksbank", provider: "generic_fints", name: "Household bank", created_at: "2026-01-03T10:00:00Z", updated_at: "2026-09-30T08:42:00Z", last_error: null, public_fields: { bank_brand: "volksbank", bank_name: "Demo Volksbank" } },
  { id: 3, source: "trade_republic", provider: "trade_republic", name: "Investment account", created_at: "2026-01-03T10:00:00Z", updated_at: "2026-09-30T08:40:00Z", last_error: null, public_fields: {} },
];

const positions = [
  { id: 1, external_id: "global-equity", isin: "DEMO00000001", name: "Global equity ETF", asset_type: "ETF", quantity: "126.4", average_buy_in: "184.30", current_price: "213.45", market_value: "26980.08", cost_value: "23295.52", gain_value: "3684.56", gain_percent: "15.82", performance_cost_value: "23295.52", currency: "EUR" },
  { id: 2, external_id: "green-bonds", isin: "DEMO00000002", name: "European bond ETF", asset_type: "ETF", quantity: "74.2", average_buy_in: "96.10", current_price: "99.25", market_value: "7364.35", cost_value: "7130.62", gain_value: "233.73", gain_percent: "3.28", performance_cost_value: "7130.62", currency: "EUR" },
  { id: 3, external_id: "digital-assets", isin: null, name: "Digital assets", asset_type: "Crypto", quantity: "1.00", average_buy_in: "3170.00", current_price: "4055.57", market_value: "4055.57", cost_value: "3170.00", gain_value: "885.57", gain_percent: "27.94", performance_cost_value: "3170.00", currency: "EUR" },
];

const assets = {
  portfolios: [{
    id: 1, connection_id: 3, source: "trade_republic", name: "Long-term portfolio",
    currency: "EUR", last_synced_at: "2026-09-30T08:40:00Z",
    total_market_value: "38400.00", total_cost_value: "33596.14",
    total_gain_value: "4803.86", total_gain_percent: "14.30",
    performance_cost_value: "33596.14", priced_positions: 3, positions,
  }],
};

const transactions = [
  { id: 101, account_id: 1, external_id: "tx-101", booking_date: "2026-09-29", amount: "3850.00", currency: "EUR", raw_text: "NORTHSTAR LABS · MONTHLY SALARY", counterparty: "Northstar Labs", kind: "income", category_id: 8, categorized_by: "rule", categorization_reason: "Recurring monthly income" },
  { id: 102, account_id: 2, external_id: "tx-102", booking_date: "2026-09-28", amount: "-82.45", currency: "EUR", raw_text: "MARKET HALL · WEEKLY GROCERIES", counterparty: "Market Hall", kind: "expense", category_id: 2, categorized_by: "llm", categorization_reason: "The merchant and booking text indicate a grocery purchase." },
  { id: 103, account_id: 2, external_id: "tx-103", booking_date: "2026-09-26", amount: "-42.80", currency: "EUR", raw_text: "HARBOUR KITCHEN · DINNER", counterparty: "Harbour Kitchen", kind: "expense", category_id: 3, categorized_by: "llm", categorization_reason: "The booking refers to a restaurant visit." },
  { id: 104, account_id: 1, external_id: "tx-104", booking_date: "2026-09-23", amount: "-18.60", currency: "EUR", raw_text: "CITY TRANSIT · MONTHLY PASS", counterparty: "City Transit", kind: "expense", category_id: 4, categorized_by: "rule", categorization_reason: "Public transport payment" },
  { id: 105, account_id: 1, external_id: "tx-105", booking_date: "2026-09-20", amount: "-1240.00", currency: "EUR", raw_text: "RIVERSIDE HOUSING · RENT", counterparty: "Riverside Housing", kind: "expense", category_id: 1, categorized_by: "rule", categorization_reason: "Recurring rent payment" },
  { id: 106, account_id: 2, external_id: "tx-106", booking_date: "2026-09-18", amount: "-16.90", currency: "EUR", raw_text: "STORYSTREAM · SUBSCRIPTION", counterparty: "StoryStream", kind: "expense", category_id: 6, categorized_by: "rule", categorization_reason: "Recurring media subscription" },
  { id: 107, account_id: 1, external_id: "tx-107", booking_date: "2026-09-14", amount: "-58.00", currency: "EUR", raw_text: "CITY THEATRE · TWO TICKETS", counterparty: "City Theatre", kind: "expense", category_id: 5, categorized_by: "llm", categorization_reason: "The merchant is a cultural venue." },
  { id: 108, account_id: 1, external_id: "tx-108", booking_date: "2026-09-10", amount: "-650.00", currency: "EUR", raw_text: "TRANSFER · RAINY-DAY FUND", counterparty: "Rainy-day fund", kind: "transfer", category_id: 7, categorized_by: "rule", categorization_reason: "Transfer between own accounts" },
  { id: 109, account_id: 3, external_id: "tx-109", booking_date: "2026-09-08", amount: "-450.00", currency: "EUR", raw_text: "INVESTMENT PLAN · GLOBAL EQUITY", counterparty: "Investment plan", kind: "expense", category_id: 7, categorized_by: "rule", categorization_reason: "Recurring investment plan" },
  { id: 110, account_id: 1, external_id: "tx-110", booking_date: "2026-09-04", amount: "-37.20", currency: "EUR", raw_text: "CORNER MARKET · GROCERIES", counterparty: "Corner Market", kind: "expense", category_id: 2, categorized_by: "llm", categorization_reason: "The merchant is a grocery retailer." },
];

const monthData = [
  [3850, 1240, 390, 180, 95, 60, 450], [3850, 1240, 420, 165, 120, 58, 450],
  [3910, 1240, 375, 205, 110, 64, 500], [3850, 1240, 440, 155, 85, 61, 500],
  [4025, 1240, 410, 190, 145, 62, 550], [3850, 1240, 395, 230, 90, 63, 550],
  [3850, 1240, 430, 175, 260, 62, 550], [3850, 1240, 405, 185, 210, 64, 600],
  [3850, 1240, 415, 195, 160, 65, 600], [0, 0, 0, 0, 0, 0, 0],
  [0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0],
];

const meta = {
  Housing: { slug: "housing", color: "#8b9cf5", color_key: "housing", icon: "house" },
  Groceries: { slug: "groceries", color: "#42c4a3", color_key: "groceries", icon: "basket" },
  Dining: { slug: "dining", color: "#f2aa67", color_key: "dining", icon: "utensils" },
  Mobility: { slug: "mobility", color: "#68a4ee", color_key: "mobility", icon: "car" },
  Leisure: { slug: "leisure", color: "#c78af2", color_key: "leisure", icon: "culture" },
  Subscriptions: { slug: "subscriptions", color: "#ec7595", color_key: "subscriptions", icon: "repeat" },
  Income: { slug: "income", color: "#4bcf91", color_key: "income", icon: "income" },
};

function segment(key: keyof typeof meta, amount: number) {
  return { key, amount: amount.toFixed(2), category_slug: meta[key].slug, color: meta[key].color, color_key: meta[key].color_key, icon: meta[key].icon };
}

const timeseries = {
  grain: "month", group_by: "category", from_date: "2026-01-01", to_date: "2026-12-31",
  buckets: monthData.slice(0, 9).map((values, index) => ({
    period: `2026-${String(index + 1).padStart(2, "0")}`,
    income_total: values[0].toFixed(2),
    expense_total: values.slice(1, 6).reduce((sum, value) => sum + value, 0).toFixed(2),
    income_segments: [segment("Income", values[0])],
    expense_segments: [
      segment("Housing", values[1]), segment("Groceries", values[2]), segment("Dining", values[3]),
      segment("Leisure", values[4]), segment("Subscriptions", values[5]),
    ],
  })),
};

const summary = {
  from_date: "2026-01-01", to_date: "2026-12-31", income: "34835.00", expense: "17645.00",
  spending: "17645.00", savings: "4750.00", net: "17190.00", transaction_count: 128,
  by_category: [
    { category_id: 1, category_name: "Housing", category_slug: "housing", color: "#8b9cf5", color_key: "housing", icon: "house", amount: "11160.00", count: 9 },
    { category_id: 2, category_name: "Groceries", category_slug: "groceries", color: "#42c4a3", color_key: "groceries", icon: "basket", amount: "3680.00", count: 42 },
    { category_id: 3, category_name: "Dining", category_slug: "dining", color: "#f2aa67", color_key: "dining", icon: "utensils", amount: "1680.00", count: 24 },
    { category_id: 5, category_name: "Leisure", category_slug: "leisure", color: "#c78af2", color_key: "leisure", icon: "culture", amount: "1275.00", count: 18 },
    { category_id: 6, category_name: "Subscriptions", category_slug: "subscriptions", color: "#ec7595", color_key: "subscriptions", icon: "repeat", amount: "550.00", count: 35 },
  ],
  income_by_category: [{ category_id: 8, category_name: "Income", category_slug: "income", color: "#4bcf91", color_key: "income", icon: "income", amount: "34835.00", count: 9 }],
};

const flow = {
  from_date: "2026-01-01", to_date: "2026-12-31", group_by: "category",
  nodes: [
    { name: "Cashflow", role: "hub", category_slug: null },
    { name: "In · Income", role: "income", category_slug: "income", color: "#4bcf91", color_key: "income", icon: "income", group_by: "category", group_key: "Income" },
    { name: "Out · Housing", role: "expense", category_slug: "housing", color: "#8b9cf5", color_key: "housing", icon: "house", group_by: "category", group_key: "Housing" },
    { name: "Out · Groceries", role: "expense", category_slug: "groceries", color: "#42c4a3", color_key: "groceries", icon: "basket", group_by: "category", group_key: "Groceries" },
    { name: "Out · Dining", role: "expense", category_slug: "dining", color: "#f2aa67", color_key: "dining", icon: "utensils", group_by: "category", group_key: "Dining" },
    { name: "Out · Leisure", role: "expense", category_slug: "leisure", color: "#c78af2", color_key: "leisure", icon: "culture", group_by: "category", group_key: "Leisure" },
    { name: "Save · Investments", role: "saving", category_slug: "savings", color: "#75ca70", color_key: "savings", icon: "savings", group_by: "category", group_key: "Savings & investments" },
  ],
  links: [
    { source: 1, target: 0, value: 34835 }, { source: 0, target: 2, value: 11160 },
    { source: 0, target: 3, value: 3680 }, { source: 0, target: 4, value: 1680 },
    { source: 0, target: 5, value: 1275 }, { source: 0, target: 6, value: 4750 },
  ],
};

const conversation = {
  id: 1, title: "Spending review", preview: "Your spending stayed below the monthly average…",
  message_count: 2, created_at: "2026-09-30T09:00:00Z", updated_at: "2026-09-30T09:01:00Z",
  messages: [
    { id: 1, role: "user", content: "How did my spending develop over the last three months?", created_at: "2026-09-30T09:00:00Z" },
    {
      id: 2,
      role: "assistant",
      content: `Your everyday spending stayed **6% below** the previous three-month average. At the same time, monthly wealth building increased steadily.

\`\`\`chart
{"type":"bar","title":"Monthly wealth building","labels":["Jul","Aug","Sep"],"series":[{"name":"Invested","values":[550,600,650]}]}
\`\`\``,
      created_at: "2026-09-30T09:01:00Z",
    },
  ],
};

const historyPoints = Array.from({ length: 18 }, (_, index) => {
  const value = 29500 + index * 520 + Math.sin(index * 0.9) * 620;
  const invested = 28500 + index * 260;
  return { timestamp: new Date(Date.UTC(2025, 4 + index, 1)).toISOString(), value: value.toFixed(2), invested_value: invested.toFixed(2), performance_percent: (((value - invested) / invested) * 100).toFixed(2) };
});

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export async function installScreenshotApi(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("finsight.lang", "en");
    window.localStorage.setItem("finsight.theme", "dark");
    window.localStorage.removeItem("finsight.demo-mode");
    window.sessionStorage.setItem("finsight.vaultToken", "screenshot-fixture-token");
  });

  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (path === "/api/vault/status") return json(route, { initialized: true, unlocked: true, recovery_configured: true, recovery_confirmed: true });
    if (path === "/api/onboarding") return json(route, { completed: true });
    if (path === "/api/accounts") return json(route, accounts);
    if (path === "/api/connections") return json(route, connections);
    if (path === "/api/sync/status") return json(route, accounts.map((account) => ({ account_id: account.id, account_name: account.name, status: "idle", last_success_at: account.balance_updated_at, last_error: null, pending_jobs: 0, latest_job_status: "done", history_from: "2026-01-01", backfill_cursor: null, latest_booking_date: "2026-09-29", earliest_booking_date: "2026-01-02" })));
    if (path === "/api/sync/connections/status") return json(route, connections.map((connection) => ({ connection_id: connection.id, pending_jobs: 0, running_jobs: 0, latest_job_status: "done", latest_job_error: null })));
    if (path === "/api/categorize/status") return json(route, { ollama_configured: true, ollama_reachable: true, phase: "idle", queue_remaining: 0, queue_total: 0, queue_processed: 0, current: null, last_done: [], llm_applied_session: 0, message: null });
    if (path === "/api/assets") return json(route, assets);
    if (path === "/api/assets/history") return json(route, { kind: url.searchParams.has("external_id") ? "instrument" : url.searchParams.has("portfolio_id") ? "portfolio" : "aggregate", label: "Total assets", currency: "EUR", estimated: false, source: "calculated", calibration: null, points: historyPoints });
    if (path === "/api/inflation/germany") return json(route, { country: "DE", currency: "EUR", source: "Screenshot fixture", points: [] });
    if (path === "/api/stats/summary") return json(route, summary);
    if (path === "/api/stats/timeseries") return json(route, timeseries);
    if (path === "/api/stats/flow") return json(route, flow);
    if (path === "/api/transactions/page") return json(route, { items: transactions, has_more: false, next_offset: null });
    if (path === "/api/transactions/groups") return json(route, []);
    if (path === "/api/categories") return json(route, categories);
    if (path === "/api/tags") return json(route, [{ id: 1, name: "Summer trip", tag_type: "trip", color: "#93c5fd", from_date: "2026-07-01", to_date: "2026-07-14", created_by: "manual" }]);
    if (path === "/api/tag-assignments") return json(route, []);
    if (path === "/api/agent/conversations") return json(route, [{ id: conversation.id, title: conversation.title, preview: conversation.preview, message_count: conversation.message_count, created_at: conversation.created_at, updated_at: conversation.updated_at }]);
    if (path === "/api/agent/conversations/1") return json(route, conversation);

    return json(route, { detail: `No screenshot fixture for ${path}` }, 404);
  });
}
