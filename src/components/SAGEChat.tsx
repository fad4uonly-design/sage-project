"use client";

import { useEffect, useRef, useState, useCallback, FormEvent } from "react";

// ── Types ────────────────────────────────────────────────────────────────────

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  routeUsed?: "direct" | "memory" | "notes" | "web" | "knowledge" | "tool";
  toolStatus?: string;
  error?: boolean;
}

interface Conversation {
  id: number;
  title: string;
  createdAt: string;
  updatedAt: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

function routeBadge(route?: ChatMessage["routeUsed"]) {
  if (!route || route === "direct") return null;
  const labels: Record<string, string> = {
    memory: "memory",
    notes: "local notes",
    knowledge: "local knowledge",
    tool: "tool",
    web: "web search",
  };
  return labels[route] ?? route;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SageIcon() {
  return (
    <span
      className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-indigo-600 text-white text-xs font-bold shrink-0"
      aria-hidden
    >
      S
    </span>
  );
}

function UserIcon() {
  return (
    <span
      className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-slate-700 text-slate-200 text-xs font-bold shrink-0"
      aria-hidden
    >
      U
    </span>
  );
}

function ToolStatusBadge({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-indigo-400 font-mono mb-1">
      <span className="h-1.5 w-1.5 rounded-full bg-indigo-400 animate-pulse" />
      {label}
    </span>
  );
}

function RouteBadge({ route }: { route?: ChatMessage["routeUsed"] }) {
  const label = routeBadge(route);
  if (!label) return null;
  return (
    <span className="mt-1 inline-block text-[10px] uppercase tracking-widest text-slate-500">
      via {label}
    </span>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  return (
    <div
      className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
      {isUser ? <UserIcon /> : <SageIcon />}
      <div className={`flex flex-col max-w-[80%] ${isUser ? "items-end" : "items-start"}`}>
        {msg.toolStatus && !isUser && (
          <ToolStatusBadge label={msg.toolStatus} />
        )}
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words ${
            isUser
              ? "bg-indigo-600 text-white rounded-tr-sm"
              : msg.error
              ? "bg-red-900/50 text-red-300 rounded-tl-sm"
              : "bg-[#1e2130] text-slate-100 rounded-tl-sm"
          }`}
        >
          {msg.content}
        </div>
        {!isUser && <RouteBadge route={msg.routeUsed} />}
      </div>
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div className="flex gap-3 flex-row">
      <SageIcon />
      <div className="flex flex-col items-start max-w-[80%]">
        <div className="rounded-2xl rounded-tl-sm px-4 py-3 bg-[#1e2130]">
          <span className="flex gap-1 items-center">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="h-1.5 w-1.5 rounded-full bg-slate-500 animate-bounce"
                style={{ animationDelay: `${i * 150}ms` }}
              />
            ))}
          </span>
        </div>
      </div>
    </div>
  );
}

function ConversationItem({
  conv,
  active,
  onClick,
}: {
  conv: Conversation;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-2 rounded-lg text-sm truncate transition-colors ${
        active
          ? "bg-indigo-600/30 text-indigo-300"
          : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
      }`}
      title={conv.title}
    >
      {conv.title}
    </button>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function SAGEChat() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // ── Scroll to bottom on new messages ────────────────────────────────────
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, loading]);

  const fetchConversations = useCallback(async () => {
    try {
      const res = await fetch("/api/sage/conversations");
      if (!res.ok) throw new Error("Failed to load conversations");
      const data = (await res.json()) as { conversations: Conversation[] };
      setConversations(data.conversations ?? []);
    } catch {
      // non-critical
    }
  }, []);

  // ── Load conversation list ────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    void fetch("/api/sage/conversations")
      .then(async (res) => {
        if (!res.ok) throw new Error("Failed to load conversations");
        return (await res.json()) as { conversations: Conversation[] };
      })
      .then((data) => {
        if (!cancelled) {
          setConversations(data.conversations ?? []);
        }
      })
      .catch(() => {
        // non-critical
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // ── Load messages for active conversation ─────────────────────────────
  const loadMessages = useCallback(async (convId: number) => {
    try {
      const res = await fetch(`/api/sage/conversations/${convId}/messages`);
      const data = (await res.json()) as {
        messages: Array<{ id: number; role: string; content: string }>;
      };
      const msgs: ChatMessage[] = (data.messages ?? []).map((m) => ({
        id: String(m.id),
        role: m.role as "user" | "assistant",
        content: m.content,
      }));
      setChatMessages(msgs);
    } catch {
      setChatMessages([]);
    }
  }, []);

  const selectConversation = useCallback(
    (convId: number) => {
      setActiveConvId(convId);
      loadMessages(convId);
    },
    [loadMessages]
  );

  // ── New conversation ──────────────────────────────────────────────────
  const newConversation = useCallback(async () => {
    setChatMessages([]);
    setActiveConvId(null);
    setInput("");
    inputRef.current?.focus();
  }, []);

  // ── Send message ──────────────────────────────────────────────────────
  const sendMessage = useCallback(
    async (e?: FormEvent) => {
      e?.preventDefault();
      const text = input.trim();
      if (!text || loading) return;

      setInput("");
      setLoading(true);

      // Optimistically add user message
      const userMsg: ChatMessage = { id: uid(), role: "user", content: text };
      setChatMessages((prev) => [...prev, userMsg]);

      try {
        const res = await fetch("/api/sage/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text,
            conversationId: activeConvId ?? undefined,
          }),
        });

        const data = (await res.json()) as {
          content?: string;
          routeUsed?: ChatMessage["routeUsed"];
          toolStatus?: string;
          modelUsed?: string;
          conversationId?: number;
          error?: string;
        };

        if (!res.ok || data.error) {
          const errMsg: ChatMessage = {
            id: uid(),
            role: "assistant",
            content: data.error ?? "An error occurred. Please try again.",
            error: true,
          };
          setChatMessages((prev) => [...prev, errMsg]);
        } else {
          const assistantMsg: ChatMessage = {
            id: uid(),
            role: "assistant",
            content: data.content ?? "",
            routeUsed: data.routeUsed,
            toolStatus: data.toolStatus,
          };
          setChatMessages((prev) => [...prev, assistantMsg]);

          // Update conversation tracking
          if (data.conversationId && data.conversationId !== activeConvId) {
            setActiveConvId(data.conversationId);
            await fetchConversations();
          } else {
            fetchConversations();
          }
        }
      } catch {
        const errMsg: ChatMessage = {
          id: uid(),
          role: "assistant",
          content:
            "Could not reach the SAGE server. Please check the connection.",
          error: true,
        };
        setChatMessages((prev) => [...prev, errMsg]);
      } finally {
        setLoading(false);
        setTimeout(() => inputRef.current?.focus(), 50);
      }
    },
    [input, loading, activeConvId, fetchConversations]
  );

  // ── Auto-resize textarea ──────────────────────────────────────────────
  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#0f1117]">

      {/* ── Sidebar ── */}
      {sidebarOpen && (
        <aside className="w-60 shrink-0 flex flex-col border-r border-white/[0.07] bg-[#0f1117]">
          {/* Brand */}
          <div className="flex items-center gap-2.5 px-4 py-5 border-b border-white/[0.07]">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-xl bg-indigo-600 text-white font-bold text-sm">
              S
            </span>
            <span className="text-base font-semibold tracking-wide text-slate-100">
              SAGE
            </span>
          </div>

          {/* New conversation */}
          <div className="px-3 pt-4 pb-2">
            <button
              onClick={newConversation}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-slate-300 bg-white/5 hover:bg-white/10 transition-colors"
            >
              <span className="text-base leading-none">+</span>
              New conversation
            </button>
          </div>

          {/* Conversation list */}
          <nav className="flex-1 overflow-y-auto px-3 py-2 space-y-0.5">
            {conversations.length === 0 && (
              <p className="text-xs text-slate-600 px-3 py-2">
                No conversations yet.
              </p>
            )}
            {conversations.map((conv) => (
              <ConversationItem
                key={conv.id}
                conv={conv}
                active={conv.id === activeConvId}
                onClick={() => selectConversation(conv.id)}
              />
            ))}
          </nav>

          {/* Footer */}
          <div className="px-4 py-3 border-t border-white/[0.07]">
            <p className="text-[10px] text-slate-600 uppercase tracking-widest">
              Personal AI · v0.1
            </p>
          </div>
        </aside>
      )}

      {/* ── Main area ── */}
      <main className="flex flex-1 flex-col min-w-0">

        {/* Header */}
        <header className="flex items-center gap-3 px-4 py-3 border-b border-white/[0.07] bg-[#0f1117]/80 backdrop-blur-sm shrink-0">
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            className="p-1.5 rounded-md text-slate-500 hover:text-slate-300 hover:bg-white/5 transition-colors"
            aria-label="Toggle sidebar"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <h1 className="text-sm font-semibold text-slate-200 tracking-wide">
            {activeConvId
              ? conversations.find((c) => c.id === activeConvId)?.title ?? "Conversation"
              : "SAGE"}
          </h1>
        </header>

        {/* Conversation area */}
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-2xl px-4 py-8 space-y-6">
            {chatMessages.length === 0 && !loading && (
              <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
                <span className="inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-600/20 text-indigo-400 text-3xl font-bold">
                  S
                </span>
                <h2 className="text-xl font-semibold text-slate-200">
                  Hello, I&apos;m SAGE
                </h2>
                <p className="text-sm text-slate-500 max-w-xs">
                  Your personal AI assistant. Ask me anything, or try:
                </p>
                <ul className="text-sm text-slate-600 space-y-1 text-left list-none">
                  {[
                    "Hello SAGE",
                    "Remember that my favourite language is TypeScript",
                    "What do you know about my preferences?",
                    "List my notes",
                    "Create note: Meeting agenda\nDiscuss Q3 goals",
                  ].map((ex) => (
                    <li key={ex}>
                      <button
                        onClick={() => {
                          setInput(ex);
                          inputRef.current?.focus();
                        }}
                        className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-slate-200 transition-colors text-left w-full font-mono text-xs"
                      >
                        {ex}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {chatMessages.map((msg) => (
              <MessageBubble key={msg.id} msg={msg} />
            ))}

            {loading && <ThinkingIndicator />}

            <div ref={bottomRef} />
          </div>
        </div>

        {/* Input area */}
        <div className="shrink-0 border-t border-white/[0.07] bg-[#0f1117]/80 backdrop-blur-sm px-4 py-3">
          <form
            onSubmit={sendMessage}
            className="mx-auto max-w-2xl flex items-end gap-3"
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={handleTextareaChange}
              onKeyDown={handleKeyDown}
              placeholder="Message SAGE…"
              rows={1}
              disabled={loading}
              className="flex-1 resize-none rounded-xl border border-white/[0.1] bg-[#1e2130] px-4 py-3 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-indigo-500/60 disabled:opacity-50 transition-colors min-h-[46px] max-h-[160px] leading-relaxed"
              style={{ height: "46px" }}
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="h-[46px] w-[46px] shrink-0 flex items-center justify-center rounded-xl bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              aria-label="Send"
            >
              {loading ? (
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M5 12h14M12 5l7 7-7 7" />
                </svg>
              )}
            </button>
          </form>
          <p className="mx-auto max-w-2xl mt-1.5 text-[10px] text-slate-700 text-center">
            Enter to send · Shift+Enter for new line
          </p>
        </div>
      </main>
    </div>
  );
}
