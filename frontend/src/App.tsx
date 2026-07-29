import { useCallback, useEffect, useState } from "react";

import { MenuIcon } from "@/components/ui/icons";
import { Banner, IconButton } from "@/components/ui/primitives";
import { LoginPage } from "@/features/auth/LoginPage";
import { Composer } from "@/features/chat/Composer";
import { EmptyState } from "@/features/chat/EmptyState";
import { MessageList, type ChatMessage } from "@/features/chat/MessageList";
import { useChat } from "@/features/chat/useChat";
import { Sidebar } from "@/features/conversations/Sidebar";
import {
  api,
  type ConversationSummary,
  type CurrentUser,
  type Overview,
} from "@/lib/api";

type Theme = "light" | "dark";

const THEME_KEY = "copilot-theme";

function readStoredTheme(): Theme | null {
  const stored = localStorage.getItem(THEME_KEY);
  return stored === "light" || stored === "dark" ? stored : null;
}

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);

  const [overview, setOverview] = useState<Overview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);

  const [theme, setTheme] = useState<Theme>(() => readStoredTheme() ?? systemTheme());
  const [navOpen, setNavOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  // --- theme -------------------------------------------------------------
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  // --- session -----------------------------------------------------------

  const signOut = useCallback(() => {
    api.logout().catch(() => {
      /* best effort; the local token is dropped either way */
    });
    setToken(null);
    setUser(null);
    setConversations([]);
    setOverview(null);
    setActiveId(null);
  }, []);

  // On load, try the httpOnly refresh cookie before showing a login form. Without this
  // a page reload always meant re-authenticating, even with a valid session.
  useEffect(() => {
    let cancelled = false;
    api
      .refresh()
      .then(({ access_token }) => {
        if (!cancelled) setToken(access_token);
      })
      .catch(() => {
        /* no live session; the login page is correct */
      })
      .finally(() => {
        if (!cancelled) setBootstrapping(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    api
      .me(token)
      .then((me) => !controller.signal.aborted && setUser(me))
      .catch(() => {
        /* the avatar falls back to a placeholder */
      });
    return () => controller.abort();
  }, [token]);

  // Refresh ahead of the 15-minute expiry.
  useEffect(() => {
    if (!token) return;
    const timer = setInterval(
      () => {
        api
          .refresh()
          .then(({ access_token }) => setToken(access_token))
          .catch(() => setToken(null));
      },
      14 * 60 * 1000
    );
    return () => clearInterval(timer);
  }, [token]);

  // --- conversations -----------------------------------------------------

  // The effect owns the fetch; callers ask for a reload by bumping the key. Calling a
  // state-setting function directly from an effect body causes cascading renders.
  const [listKey, setListKey] = useState(0);
  const reloadConversations = useCallback(() => setListKey((k) => k + 1), []);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api
      .listConversations(token)
      .then((list) => {
        if (!cancelled) setConversations(list);
      })
      .catch(() => {
        /* the list simply stays as it was */
      })
      .finally(() => {
        if (!cancelled) setLoadingList(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, listKey]);

  // The overview is refetched on the same key as the conversation list, so a turn that
  // moved a number updates the strip too.
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api
      .overview(token)
      .then((data) => {
        if (!cancelled) setOverview(data);
      })
      .catch(() => {
        /* the strip stays as it was, or shows skeletons on first load */
      })
      .finally(() => {
        if (!cancelled) setOverviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, listKey]);

  // --- chat --------------------------------------------------------------

  const { messages, setMessages, busy, activeTool, send, cancel } = useChat({
    token: token ?? "",
    conversationId: activeId,
    onConversationCreated: setActiveId,
    onTurnComplete: reloadConversations,
    onAuthExpired: () => {
      setNotice("Your session expired. Please sign in again.");
      signOut();
    },
  });

  const openConversation = useCallback(
    async (id: string) => {
      if (!token) return;
      setActiveId(id);
      setNavOpen(false);
      try {
        const detail = await api.getConversation(token, id);
        setMessages(
          detail.messages.map<ChatMessage>((m) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            tools: m.tools,
          }))
        );
      } catch {
        setNotice("That conversation could not be loaded.");
      }
    },
    [setMessages, token]
  );

  const startNew = useCallback(() => {
    setActiveId(null);
    setMessages([]);
    setNavOpen(false);
  }, [setMessages]);

  const renameConversation = useCallback(
    async (id: string, title: string) => {
      if (!token) return;
      // Optimistic: the sidebar updates immediately and reconciles on the next load.
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, title } : c))
      );
      try {
        await api.renameConversation(token, id, title);
      } catch {
        void reloadConversations();
      }
    },
    [reloadConversations, token]
  );

  const deleteConversation = useCallback(
    async (id: string) => {
      if (!token) return;
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (id === activeId) startNew();
      try {
        await api.deleteConversation(token, id);
      } catch {
        void reloadConversations();
      }
    },
    [activeId, reloadConversations, startNew, token]
  );

  // --- render ------------------------------------------------------------

  if (bootstrapping) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-sunken">
        <span className="sr-only">Loading</span>
      </div>
    );
  }

  if (!token) {
    return <LoginPage onSignIn={setToken} />;
  }

  const activeTitle =
    conversations.find((c) => c.id === activeId)?.title ?? "New conversation";

  return (
    <div className="flex h-screen overflow-hidden bg-surface-sunken">
      {/* Navigation. A drawer below lg, a fixed rail above it. */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-72 border-r border-line transition-transform duration-200 lg:static lg:translate-x-0 ${
          navOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <Sidebar
          conversations={conversations}
          activeId={activeId}
          loading={loadingList}
          user={user}
          overview={overview}
          overviewLoading={overviewLoading}
          theme={theme}
          onSelect={openConversation}
          onNew={startNew}
          onRename={renameConversation}
          onDelete={deleteConversation}
          onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          onSignOut={signOut}
          onClose={() => setNavOpen(false)}
        />
      </aside>

      {navOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col bg-surface">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-3 sm:px-4">
          <IconButton
            label="Open navigation"
            onClick={() => setNavOpen(true)}
            className="lg:hidden"
          >
            <MenuIcon />
          </IconButton>
          <h1 className="min-w-0 flex-1 truncate text-sm font-medium text-ink">
            {messages.length ? activeTitle : "New conversation"}
          </h1>
        </header>

        {notice && (
          <div className="px-4 pt-3 sm:px-6">
            <Banner onDismiss={() => setNotice(null)}>{notice}</Banner>
          </div>
        )}

        <main className="min-h-0 flex-1">
          {messages.length === 0 ? (
            <EmptyState user={user} onPick={send} />
          ) : (
            <MessageList messages={messages} user={user} activeTool={activeTool} />
          )}
        </main>

        <div className="shrink-0 border-t border-line bg-surface px-4 py-3 sm:px-6">
          <div className="mx-auto max-w-3xl">
            <Composer onSubmit={send} onCancel={cancel} busy={busy} autoFocus />
            <p className="mt-2 text-center text-2xs text-ink-muted">
              Answers come from your tenant's data. Expand any tool trace to check the
              query behind a number.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
