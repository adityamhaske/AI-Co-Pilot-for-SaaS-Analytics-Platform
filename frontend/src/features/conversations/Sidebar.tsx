import { useMemo, useState } from "react";

import {
  ChatIcon,
  CloseIcon,
  LogoutIcon,
  MoonIcon,
  PencilIcon,
  PlusIcon,
  SparkIcon,
  SunIcon,
  TrashIcon,
} from "@/components/ui/icons";
import { Badge, Button, IconButton, Input, Skeleton } from "@/components/ui/primitives";
import { MetricStrip } from "@/features/overview/MetricStrip";
import type { ConversationSummary, CurrentUser, Overview } from "@/lib/api";
import { formatValue, initialsFor, relativeDateGroup, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

const GROUP_ORDER = [
  "Today",
  "Yesterday",
  "Previous 7 days",
  "Previous 30 days",
  "Earlier",
];

/**
 * Conversation history and account controls.
 *
 * Grouped by recency rather than shown as one long list, because "when did I ask that"
 * is how people actually search their own history.
 */
export function Sidebar({
  conversations,
  activeId,
  loading,
  user,
  overview,
  overviewLoading,
  theme,
  onSelect,
  onNew,
  onRename,
  onDelete,
  onToggleTheme,
  onSignOut,
  onClose,
}: {
  conversations: ConversationSummary[];
  activeId: string | null;
  loading: boolean;
  user: CurrentUser | null;
  overview: Overview | null;
  overviewLoading: boolean;
  theme: "light" | "dark";
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  onToggleTheme: () => void;
  onSignOut: () => void;
  onClose?: () => void;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const grouped = useMemo(() => {
    const buckets = new Map<string, ConversationSummary[]>();
    for (const c of conversations) {
      const key = relativeDateGroup(c.updated_at);
      const list = buckets.get(key) ?? [];
      list.push(c);
      buckets.set(key, list);
    }
    return GROUP_ORDER.filter((g) => buckets.has(g)).map((g) => ({
      label: g,
      items: buckets.get(g)!,
    }));
  }, [conversations]);

  const startRename = (c: ConversationSummary) => {
    setEditingId(c.id);
    setDraft(c.title);
    setConfirmingId(null);
  };

  const commitRename = () => {
    if (editingId && draft.trim()) onRename(editingId, draft.trim());
    setEditingId(null);
  };

  return (
    <div className="flex h-full flex-col bg-surface-sunken">
      {/* Brand */}
      <div className="flex h-14 items-center gap-2 border-b border-line px-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-accent-ink">
          <SparkIcon className="h-4 w-4" />
        </div>
        <span className="min-w-0 flex-1 truncate text-sm font-semibold text-ink">
          Analytics Co-pilot
        </span>
        {user && (
          <Badge
            className={
              user.role === "admin"
                ? "border-accent/40 bg-accent-subtle text-accent"
                : user.role === "analyst"
                  ? "border-line bg-surface-hover text-ink-secondary"
                  : "border-line text-ink-muted"
            }
          >
            {user.role}
          </Badge>
        )}
        {onClose && (
          <IconButton label="Close navigation" size="sm" onClick={onClose} className="lg:hidden">
            <CloseIcon />
          </IconButton>
        )}
      </div>

      <div className="space-y-3 p-3">
        <Button variant="secondary" onClick={onNew} className="w-full justify-start">
          <PlusIcon />
          New conversation
        </Button>

        {/* Live figures from the same registry the agent queries, so this strip and the
            answers below it can never disagree. */}
        <div>
          <h2 className="mb-1.5 px-0.5 text-2xs font-semibold uppercase tracking-wide text-ink-muted">
            This month
          </h2>
          <MetricStrip tiles={overview?.tiles ?? []} loading={overviewLoading} />
        </div>
      </div>

      {/* History */}
      <nav aria-label="Conversation history" className="scroll-region flex-1 overflow-y-auto px-2 pb-2">
        {loading && (
          <div className="space-y-2 px-1 py-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        )}

        {!loading && conversations.length === 0 && (
          <p className="px-3 py-6 text-center text-xs text-ink-muted">
            Your conversations will appear here.
          </p>
        )}

        {grouped.map((group) => (
          <div key={group.label} className="mb-3">
            <h2 className="px-3 py-1.5 text-2xs font-semibold uppercase tracking-wide text-ink-muted">
              {group.label}
            </h2>
            <ul className="space-y-0.5">
              {group.items.map((c) => {
                const active = c.id === activeId;
                const editing = editingId === c.id;
                const confirming = confirmingId === c.id;

                return (
                  <li key={c.id}>
                    {editing ? (
                      <div className="px-1 py-0.5">
                        <Input
                          autoFocus
                          value={draft}
                          aria-label="Conversation title"
                          onChange={(e) => setDraft(e.target.value)}
                          onBlur={commitRename}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") commitRename();
                            if (e.key === "Escape") setEditingId(null);
                          }}
                          className="h-8 text-sm"
                        />
                      </div>
                    ) : (
                      <div
                        className={cn(
                          "group flex items-center gap-1 rounded-md pr-1 transition-colors",
                          active
                            ? "bg-accent-subtle"
                            : "hover:bg-surface-hover"
                        )}
                      >
                        <button
                          type="button"
                          onClick={() => onSelect(c.id)}
                          aria-current={active ? "page" : undefined}
                          className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2.5 py-2 text-left"
                        >
                          <ChatIcon
                            className={cn(
                              "h-3.5 w-3.5 shrink-0",
                              active ? "text-accent" : "text-ink-muted"
                            )}
                          />
                          <span
                            className={cn(
                              "truncate text-sm",
                              active ? "font-medium text-accent" : "text-ink-secondary"
                            )}
                          >
                            {c.title}
                          </span>
                        </button>

                        {confirming ? (
                          <div className="flex shrink-0 items-center gap-0.5 pr-1">
                            <button
                              type="button"
                              onClick={() => {
                                onDelete(c.id);
                                setConfirmingId(null);
                              }}
                              className="rounded px-1.5 py-0.5 text-2xs font-semibold text-danger hover:underline"
                            >
                              Delete
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmingId(null)}
                              className="rounded px-1.5 py-0.5 text-2xs text-ink-muted hover:underline"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          // Revealed on hover, but always reachable by keyboard.
                          <div className="flex shrink-0 items-center opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                            <IconButton
                              label={`Rename ${c.title}`}
                              size="sm"
                              onClick={() => startRename(c)}
                            >
                              <PencilIcon className="h-3.5 w-3.5" />
                            </IconButton>
                            <IconButton
                              label={`Delete ${c.title}`}
                              size="sm"
                              onClick={() => setConfirmingId(c.id)}
                              className="hover:text-danger"
                            >
                              <TrashIcon className="h-3.5 w-3.5" />
                            </IconButton>
                          </div>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Account */}
      <div className="border-t border-line p-2">
        {overview && (
          // Which model answered, and what today has cost. Both are facts a user of an
          // LLM product should not have to guess at.
          <div className="mb-1 flex items-center justify-between gap-2 px-2 py-1 text-2xs text-ink-muted">
            <span className="flex min-w-0 items-center gap-1.5">
              <span
                aria-hidden="true"
                className="h-1.5 w-1.5 shrink-0 rounded-full bg-success"
              />
              <span className="truncate font-mono">{overview.model}</span>
            </span>
            <span
              className="shrink-0 tabular-nums"
              title={`Rolling 24-hour spend against a ${formatValue(
                overview.daily_limit_usd,
                "currency_usd"
              )} limit`}
            >
              {formatValue(overview.spend_today_usd, "currency_usd")} today
            </span>
          </div>
        )}
        <div className="flex items-center gap-2 rounded-md px-2 py-1.5">
          <div
            aria-hidden="true"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-active text-2xs font-semibold text-ink-secondary"
          >
            {initialsFor(user)}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-ink">
              {user?.email ?? "…"}
            </p>
            <p className="text-2xs text-ink-muted">
              {user ? titleCase(user.role) : ""}
            </p>
          </div>
          <IconButton
            label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            size="sm"
            onClick={onToggleTheme}
          >
            {theme === "dark" ? <SunIcon className="h-3.5 w-3.5" /> : <MoonIcon className="h-3.5 w-3.5" />}
          </IconButton>
          <IconButton label="Sign out" size="sm" onClick={onSignOut}>
            <LogoutIcon className="h-3.5 w-3.5" />
          </IconButton>
        </div>
      </div>
    </div>
  );
}
