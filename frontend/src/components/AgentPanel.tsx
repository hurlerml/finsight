import { FormEvent, lazy, Suspense, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUp, Check, Globe, History, LoaderCircle, MessageSquare, Pencil, Plus, SlidersHorizontal, Trash2, X } from "lucide-react";

import {
  api,
  type AgentConversationSummary,
  type AgentMessage,
  type AgentStreamEvent,
  type CategorizeStatus,
} from "@/api/client";
import type { AssistantPresence } from "@/components/AssistantAvatar";
import { Button } from "@/components/ui";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type ChatMessage = { id?: number; role: "agent" | "user"; text: string };
type AgentActivity = Extract<AgentStreamEvent, { type: "activity" }>;
type ChartSpec = { type: "line" | "bar" | "stacked_bar" | "donut"; title: string; labels: string[]; series: { name: string; values: number[] }[] };
const ChatMarkdown = lazy(() => import("@/components/ChatMarkdown"));

function ChatChart({ spec }: { spec: ChartSpec }) {
  const data = spec.labels.map((label, index) => Object.fromEntries([
    ["label", label],
    ...spec.series.map((series, seriesIndex) => [`series${seriesIndex}`, series.values[index]]),
  ]));
  return (
    <div className="mt-3 rounded-2xl border border-border/40 bg-card/35 p-3">
      <p className="mb-2 text-xs font-semibold">{spec.title}</p>
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {spec.type === "line" ? (
            <LineChart data={data} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
              <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.35} vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={34} />
              <Tooltip contentStyle={{ borderRadius: "0.75rem", fontSize: "0.7rem" }} />
              {spec.series.map((series, index) => <Line key={series.name} dataKey={`series${index}`} name={series.name} stroke={`hsl(var(--chart-income-${(index % 5) + 1}))`} strokeWidth={2} dot={false} />)}
            </LineChart>
          ) : spec.type === "donut" ? (
            <PieChart>
              <Tooltip contentStyle={{ borderRadius: "0.75rem", fontSize: "0.7rem" }} />
              <Pie
                data={spec.labels.map((label, index) => ({ name: label, value: spec.series[0]?.values[index] ?? 0 }))}
                dataKey="value"
                nameKey="name"
                innerRadius="52%"
                outerRadius="78%"
                paddingAngle={2}
                stroke="hsl(var(--card))"
                strokeWidth={2}
              >
                {spec.labels.map((label, index) => <Cell key={`${label}-${index}`} fill={`hsl(var(--chart-income-${(index % 5) + 1}))`} />)}
              </Pie>
            </PieChart>
          ) : (
            <BarChart data={data} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
              <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.35} vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={34} />
              <Tooltip contentStyle={{ borderRadius: "0.75rem", fontSize: "0.7rem" }} />
              {spec.series.map((series, index) => <Bar key={series.name} dataKey={`series${index}`} name={series.name} stackId={spec.type === "stacked_bar" ? "stack" : undefined} fill={`hsl(var(--chart-income-${(index % 5) + 1}))`} radius={[4, 4, 0, 0]} />)}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function messageParts(text: string) {
  const match = text.match(/```chart\s*([\s\S]*?)```/i);
  if (!match) return { text, chart: null as ChartSpec | null };
  try {
    const parsed = JSON.parse(match[1]);
    return { text: text.replace(match[0], "").trim(), chart: (parsed.chart ?? parsed) as ChartSpec };
  }
  catch { return { text, chart: null as ChartSpec | null }; }
}

export function AgentPanel({
  status,
  onPresenceChange,
  demoMode = false,
}: {
  status: CategorizeStatus | null;
  onPresenceChange?: (presence: AssistantPresence) => void;
  demoMode?: boolean;
}) {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "agent", text: t("agent.welcome") },
  ]);
  const [contextMessages, setContextMessages] = useState<AgentMessage[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<AgentConversationSummary[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [editingMessageId, setEditingMessageId] = useState<number | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [activities, setActivities] = useState<AgentActivity[]>([]);
  const [sending, setSending] = useState(false);
  const [webSearchEnabled, setWebSearchEnabled] = useState(true);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches
  );
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const toolsRef = useRef<HTMLDivElement>(null);
  const historyInitializedRef = useRef(false);
  // A presentation session may still browse the existing chat history, but
  // it must not send a new request with financial context to the agent.
  const modelAvailable = status?.ollama_reachable === true && !demoMode;

  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const update = () => setIsMobile(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  const showConversation = async (id: number) => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const conversation = await api.agentConversation(id);
      setConversationId(conversation.id);
      setContextMessages([]);
      setMessages(conversation.messages.map((message) => ({
        id: message.id,
        role: message.role === "assistant" ? "agent" : "user",
        text: message.content,
      })));
      setHistoryOpen(false);
      setEditingMessageId(null);
      setComposerError(null);
      setActivities([]);
      setInput("");
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : t("agent.historyLoadFailed"));
    } finally {
      setHistoryLoading(false);
    }
  };

  const refreshConversations = async () => {
    const items = await api.agentConversations();
    setConversations(items);
    return items;
  };

  const startNewConversation = () => {
    setConversationId(null);
    setContextMessages([]);
    setMessages([{ role: "agent", text: t("agent.welcome") }]);
    setInput("");
    setEditingMessageId(null);
    setComposerError(null);
    setActivities([]);
    setHistoryOpen(false);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  };

  useEffect(() => {
    if (historyInitializedRef.current) return;
    historyInitializedRef.current = true;
    let cancelled = false;
    setHistoryLoading(true);
    setHistoryError(null);
    api.agentConversations()
      .then(async (items) => {
        if (cancelled) return;
        setConversations(items);
        if (items[0]) {
          const conversation = await api.agentConversation(items[0].id);
          if (cancelled) return;
          setConversationId(conversation.id);
          setContextMessages([]);
          setMessages(conversation.messages.map((message) => ({
            id: message.id,
            role: message.role === "assistant" ? "agent" : "user",
            text: message.content,
          })));
        }
      })
      .catch((error) => {
        if (cancelled) return;
        historyInitializedRef.current = false;
        setHistoryError(error instanceof Error ? error.message : t("agent.historyLoadFailed"));
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [demoMode, t]);

  useEffect(() => {
    if (!modelAvailable) return;
    window.setTimeout(() => inputRef.current?.focus(), 220);
  }, [modelAvailable]);

  // Keep the composer compact for short prompts, but let it grow like a
  // modern chat composer until the content itself becomes scrollable.
  useEffect(() => {
    const textarea = inputRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    const maxHeight = 160;
    const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [input]);

  useEffect(() => {
    if (!toolsOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!toolsRef.current?.contains(event.target as Node)) setToolsOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setToolsOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [toolsOpen]);

  useEffect(() => {
    const scrollContainer = chatScrollRef.current;
    if (!scrollContainer) return;
    scrollContainer.scrollTo({
      top: scrollContainer.scrollHeight,
      behavior: sending ? "auto" : "smooth",
    });
  }, [messages, sending]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!modelAvailable || sending) return;
    const text = input.trim();
    if (!text) return;
    const replacedId = editingMessageId;
    const previousMessages = messages;
    const replacedIndex = replacedId === null
      ? -1
      : messages.findIndex((message) => message.id === replacedId && message.role === "user");
    if (replacedId !== null && replacedIndex < 0) return;
    const retainedMessages = replacedIndex >= 0 ? messages.slice(0, replacedIndex) : messages;
    const optimisticMessages: ChatMessage[] = [
      ...retainedMessages,
      { role: "user", text },
    ];
    setMessages(optimisticMessages);
    setInput("");
    setEditingMessageId(null);
    setComposerError(null);
    setActivities([]);
    setSending(true);
    try {
      const history: AgentMessage[] = [
        ...contextMessages,
        { role: "user", content: text },
      ];
      let streamedText = "";
      let streamUpdateTimer: number | undefined;
      const clearStreamUpdateTimer = () => {
        if (streamUpdateTimer !== undefined) {
          window.clearTimeout(streamUpdateTimer);
          streamUpdateTimer = undefined;
        }
      };
      const scheduleStreamUpdate = () => {
        if (streamUpdateTimer !== undefined) return;
        // Limit UI/Markdown work while the model emits many small chunks.
        // The answer is still streamed, but the phone only needs to repaint
        // the visible message around twenty times per second.
        streamUpdateTimer = window.setTimeout(() => {
          streamUpdateTimer = undefined;
          setMessages([
            ...optimisticMessages,
            { role: "agent", text: streamedText },
          ]);
        }, 50);
      };
      const response = await api.agentChatStream(
        history,
        conversationId,
        replacedId,
        (event) => {
          if (event.type === "answer_reset") {
            clearStreamUpdateTimer();
            streamedText = "";
            setMessages(optimisticMessages);
            return;
          }
          if (event.type === "token") {
            streamedText += event.content;
            scheduleStreamUpdate();
            return;
          }
          setActivities((current) => [...current, event].slice(-4));
        },
        webSearchEnabled,
      );
      clearStreamUpdateTimer();
      setConversationId(response.conversation_id);
      setContextMessages(response.context);
      setMessages([
        ...retainedMessages,
        { id: response.user_message_id, role: "user", text },
        { id: response.assistant_message_id, role: "agent", text: response.message.content },
      ]);
      void refreshConversations().catch(() => undefined);
    } catch (error) {
      const detail = error instanceof Error ? error.message : t("agent.requestFailed");
      setMessages(previousMessages);
      setInput(text);
      setEditingMessageId(replacedId);
      setComposerError(t("agent.requestFailedDetail", { detail }));
    } finally {
      setActivities([]);
      setSending(false);
    }
  };

  const editMessage = (message: ChatMessage) => {
    if (message.role !== "user" || message.id === undefined || sending) return;
    setEditingMessageId(message.id);
    setInput(message.text);
    setComposerError(null);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  };

  const cancelEditing = () => {
    setEditingMessageId(null);
    setInput("");
    setComposerError(null);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  };

  const toggleHistory = async () => {
    const nextOpen = !historyOpen;
    setHistoryOpen(nextOpen);
    setHistoryError(null);
    if (!nextOpen) return;
    setHistoryLoading(true);
    try {
      await refreshConversations();
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : t("agent.historyLoadFailed"));
    } finally {
      setHistoryLoading(false);
    }
  };

  const removeConversation = async (id: number) => {
    if (!window.confirm(t("agent.historyDeleteConfirm"))) return;
    try {
      await api.deleteAgentConversation(id);
      const remaining = conversations.filter((conversation) => conversation.id !== id);
      setConversations(remaining);
      if (conversationId === id) startNewConversation();
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : t("agent.historyDeleteFailed"));
    }
  };

  const lastMessage = messages[messages.length - 1];
  const answerIsStreaming = sending
    && lastMessage?.role === "agent"
    && lastMessage.id === undefined;
  const presence: AssistantPresence = answerIsStreaming
    ? "speaking"
    : sending
      ? "thinking"
      : input.trim()
        ? "listening"
        : "idle";

  useEffect(() => {
    onPresenceChange?.(presence);
  }, [onPresenceChange, presence]);

  return (
      <section
        aria-label={t("agent.title")}
        className="glass-surface flex h-full min-h-0 w-full flex-col overflow-hidden rounded-[1.65rem] sm:h-full sm:min-h-0"
      >
        <header className="flex items-center justify-end gap-1 px-3 pb-2 pt-3 sm:px-4 sm:pt-4">
          <Button variant="ghost" className={`h-9 w-9 rounded-full p-0 ${historyOpen ? "bg-muted" : ""}`} onClick={toggleHistory} aria-label={t("agent.history")}>
            <History className="h-4 w-4" />
          </Button>
          <Button variant="ghost" className="h-9 w-9 rounded-full p-0" onClick={startNewConversation} aria-label={t("agent.newConversation")}>
            <Plus className="h-4 w-4" />
          </Button>
        </header>

        <div ref={chatScrollRef} className="agent-chat__scroll min-h-0 flex-1 space-y-5 overflow-y-auto px-4 pb-4 sm:px-5">
          {demoMode ? (
            <div className="rounded-2xl bg-warning/10 px-3.5 py-3 text-sm text-warning ring-1 ring-warning/20">
              <p className="font-medium">{t("agent.demoModeTitle")}</p>
              <p className="mt-0.5 text-xs opacity-80">{t("agent.demoModeHint")}</p>
            </div>
          ) : !modelAvailable && (
            <div className="rounded-2xl bg-danger/10 px-3.5 py-3 text-sm text-danger ring-1 ring-danger/20">
              <p className="font-medium">{t("agent.offlineTitle")}</p>
              <p className="mt-0.5 text-xs opacity-80">{t("agent.offlineHint")}</p>
            </div>
          )}
          {historyOpen ? (
            <section className="space-y-3" aria-label={t("agent.history")}>
              <div>
                <h3 className="text-sm font-semibold">{t("agent.history")}</h3>
                <p className="text-xs text-muted-foreground">{t("agent.historyHint")}</p>
              </div>
              {historyError && (
                <p className="rounded-xl bg-danger/10 px-3 py-2 text-xs text-danger">{historyError}</p>
              )}
              {historyLoading && conversations.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">{t("common.loading")}</p>
              ) : conversations.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-10 text-center text-muted-foreground">
                  <MessageSquare className="h-6 w-6 opacity-55" />
                  <p className="text-sm">{t("agent.historyEmpty")}</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {conversations.map((conversation) => (
                    <div
                      key={conversation.id}
                      className={`group flex items-center gap-2 rounded-2xl border p-1.5 transition ${conversation.id === conversationId ? "border-primary/30 bg-primary/5" : "border-border/45 bg-card/30 hover:bg-card/60"}`}
                    >
                      <button
                        type="button"
                        onClick={() => showConversation(conversation.id)}
                        disabled={historyLoading}
                        className="min-w-0 flex-1 rounded-xl px-2 py-1.5 text-left disabled:opacity-55"
                      >
                        <span className="block truncate text-sm font-medium">{conversation.title}</span>
                        <span className="mt-0.5 block truncate text-xs text-muted-foreground">{conversation.preview}</span>
                        <span className="mt-1 block text-[0.67rem] text-muted-foreground/75">
                          {new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(conversation.updated_at))}
                          {" · "}{t("agent.messageCount", { count: conversation.message_count })}
                        </span>
                      </button>
                      <Button
                        variant="ghost"
                        className="h-8 w-8 shrink-0 rounded-full p-0 text-muted-foreground hover:text-danger"
                        onClick={() => removeConversation(conversation.id)}
                        aria-label={t("agent.historyDelete")}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </section>
          ) : <div className="space-y-3" aria-live="polite">
            {messages.map((message, index) => {
              const parts = messageParts(message.text);
              return (
              <div key={message.id ?? `local-${index}`} className={`group flex items-end gap-1 ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                {message.role === "user" && message.id !== undefined && (
                  <Button
                    variant="ghost"
                    className="h-7 w-7 shrink-0 rounded-full p-0 text-primary/65 hover:bg-primary/10 hover:text-primary sm:opacity-0 sm:transition-opacity sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
                    onClick={() => editMessage(message)}
                    disabled={sending}
                    aria-label={t("agent.editMessage")}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                )}
                <div className={`min-w-0 max-w-[88%] overflow-hidden rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${message.role === "user" ? "rounded-br-md bg-primary text-primary-foreground" : "rounded-bl-md bg-muted/65 text-foreground"}`}>
                  <Suspense fallback={<span className="whitespace-pre-wrap">{message.text}</span>}>
                    <ChatMarkdown
                      text={parts.text}
                      streaming={sending && message.role === "agent" && message.id === undefined}
                    />
                  </Suspense>
                  {parts.chart && <ChatChart spec={parts.chart} />}
                </div>
              </div>
              );
            })}
            {sending && activities.length > 0 && (
              <div className="flex justify-start" role="status" aria-live="polite">
                <div className="max-w-[92%] space-y-1.5 rounded-2xl rounded-bl-md bg-muted/45 px-3.5 py-2.5 text-xs text-muted-foreground">
                  {activities.map((activity, index) => {
                    const finished = activity.code.endsWith("_loaded")
                      || activity.code.endsWith("_calculated")
                      || activity.code.endsWith("_searched")
                      || activity.code === "tool_finished";
                    return (
                      <div key={`${activity.code}-${index}`} className="flex items-center gap-2">
                        {finished ? (
                          <Check className="h-3.5 w-3.5 shrink-0 text-accent" />
                        ) : (
                          <LoaderCircle className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
                        )}
                        <span>{t(`agent.activity.${activity.code}`, {
                          count: activity.count,
                          offset: activity.offset,
                        })}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            {sending && !answerIsStreaming && (
              <div className="flex justify-start" aria-label={t("agent.thinking")}>
                <div className="flex items-center gap-1 rounded-2xl rounded-bl-md bg-muted/65 px-3.5 py-3">
                  {[0, 1, 2].map((dot) => (
                    <span
                      key={dot}
                      className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/65"
                      style={{ animationDelay: `${dot * 160}ms` }}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>}

          {!historyOpen && messages.length === 1 && (
            <div className="flex flex-wrap gap-2">
              {["agent.promptCleanup", "agent.promptMonth", "agent.promptTransfers"].map((key) => (
                <button key={key} type="button" disabled={!modelAvailable} onClick={() => setInput(t(key))} className="rounded-full border border-border/60 bg-card/35 px-3 py-1.5 text-left text-xs text-muted-foreground transition hover:bg-card/70 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-card/35 disabled:hover:text-muted-foreground">
                  {t(key)}
                </button>
              ))}
            </div>
          )}
        </div>

        {!historyOpen && <form onSubmit={submit} className="border-t border-border/45 bg-card/30 p-3 pb-[max(.75rem,env(safe-area-inset-bottom))] sm:p-4">
          {editingMessageId !== null && (
            <div className="mb-2 flex items-center gap-2 px-1 text-xs text-muted-foreground">
              <Pencil className="h-3.5 w-3.5 text-primary" />
              <span className="min-w-0 flex-1 truncate">{t("agent.editingMessage")}</span>
              <button type="button" onClick={cancelEditing} className="rounded-full p-1 transition hover:bg-muted" aria-label={t("agent.cancelEdit")}>
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
          {composerError && (
            <p className="mb-2 rounded-xl bg-danger/10 px-3 py-2 text-xs text-danger">{composerError}</p>
          )}
          <div className="form-control flex min-h-12 items-end gap-2 rounded-2xl p-1.5 pl-3">
            <div ref={toolsRef} className="relative shrink-0">
              {toolsOpen && (
                <div
                  role="dialog"
                  aria-label={t("agent.tools")}
                  className="absolute bottom-[calc(100%+0.5rem)] left-0 z-30 w-[min(18rem,calc(100vw-2rem))] rounded-2xl border border-white/45 bg-card/95 p-2.5 text-card-foreground shadow-[0_18px_45px_-24px_hsl(var(--glass-shadow)/0.8)] backdrop-blur-2xl"
                >
                  <div className="mb-1 flex items-center justify-between px-2 py-1">
                    <span className="text-xs font-semibold text-foreground">{t("agent.tools")}</span>
                    <span className="text-[0.65rem] text-muted-foreground">{t("agent.toolsHint")}</span>
                  </div>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2.5 rounded-xl px-2 py-2 text-left transition hover:bg-muted/60"
                    onClick={() => setWebSearchEnabled((enabled) => !enabled)}
                    aria-label={t(webSearchEnabled ? "agent.webSearchOn" : "agent.webSearchOff")}
                    aria-pressed={webSearchEnabled}
                  >
                    <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${webSearchEnabled ? "bg-primary/12 text-primary" : "bg-muted/70 text-muted-foreground"}`}>
                      <Globe className="h-4 w-4" aria-hidden />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs font-semibold">{t("agent.webSearchLabel")}</span>
                      <span className="block text-[0.68rem] text-muted-foreground">
                        {t(webSearchEnabled ? "agent.webSearchStatusOn" : "agent.webSearchStatusOff")}
                      </span>
                    </span>
                    <span className={`relative h-5 w-9 shrink-0 rounded-full transition ${webSearchEnabled ? "bg-primary" : "bg-muted-foreground/35"}`} aria-hidden>
                      <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${webSearchEnabled ? "translate-x-4" : "translate-x-0.5"}`} />
                    </span>
                  </button>
                </div>
              )}
              <Button
                type="button"
                variant="ghost"
                className={`h-8 w-8 shrink-0 rounded-xl p-0 ${toolsOpen ? "bg-muted text-foreground" : "text-muted-foreground"}`}
                onClick={() => setToolsOpen((open) => !open)}
                aria-label={t("agent.tools")}
                aria-expanded={toolsOpen}
                aria-haspopup="dialog"
                title={t("agent.tools")}
              >
                <SlidersHorizontal className="h-4 w-4" aria-hidden />
              </Button>
            </div>
            <textarea
              ref={inputRef}
              value={input}
              rows={1}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !isMobile) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder={demoMode ? t("agent.demoModePlaceholder") : modelAvailable ? t("agent.placeholder") : t("agent.offlinePlaceholder")}
              disabled={!modelAvailable || sending}
              className="min-h-9 max-h-40 min-w-0 flex-1 resize-none overflow-y-hidden border-0 bg-transparent px-0.5 py-2 text-base leading-5 outline-none focus:ring-0 sm:text-sm disabled:cursor-not-allowed disabled:opacity-55"
            />
            <Button type="submit" className="h-9 w-9 shrink-0 rounded-xl p-0 disabled:cursor-not-allowed disabled:opacity-35" disabled={!modelAvailable || sending || !input.trim()} aria-label={editingMessageId !== null ? t("agent.resend") : t("agent.send")}>
              <ArrowUp className="h-4 w-4" />
            </Button>
          </div>
        </form>}
      </section>
  );
}
