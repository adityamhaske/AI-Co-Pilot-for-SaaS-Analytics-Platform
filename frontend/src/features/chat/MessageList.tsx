import { useEffect, useRef } from "react";

import { SparkIcon } from "@/components/ui/icons";
import { Skeleton } from "@/components/ui/primitives";
import type { ErrorKind } from "@/features/chat/errorNotice";
import { noticeFor } from "@/features/chat/errorNotice";
import { ToolTrace } from "@/features/chat/ToolTrace";
import type { CurrentUser } from "@/lib/api";
import { initialsFor } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: { name: string; input?: Record<string, unknown>; data?: unknown }[];
  error?: string;
  /** Why the turn stopped. Governs how the notice reads — see `noticeFor`. */
  errorKind?: ErrorKind;
  /** True while tokens are still arriving for this message. */
  streaming?: boolean;
}

function Avatar({ user, role }: { user: CurrentUser | null; role: ChatMessage["role"] }) {
  if (role === "assistant") {
    return (
      <div
        aria-hidden="true"
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent-subtle text-accent"
      >
        <SparkIcon className="h-4 w-4" />
      </div>
    );
  }
  return (
    <div
      aria-hidden="true"
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-active text-2xs font-semibold text-ink-secondary"
    >
      {initialsFor(user)}
    </div>
  );
}

function MessageRow({
  message,
  user,
  activeTool,
}: {
  message: ChatMessage;
  user: CurrentUser | null;
  activeTool: string | null;
}) {
  const isUser = message.role === "user";
  const showThinking =
    message.streaming && !message.content && !message.tools.length && !message.error;

  return (
    <article
      className="flex gap-3 px-1 animate-fade-in-up"
      aria-label={isUser ? "Your question" : "Assistant answer"}
    >
      <Avatar user={user} role={message.role} />

      <div className="min-w-0 flex-1 pb-1">
        <div className="mb-1 text-2xs font-semibold uppercase tracking-wide text-ink-muted">
          {isUser ? "You" : "Co-pilot"}
        </div>

        {showThinking ? (
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <Skeleton className="h-3 w-3 rounded-full" />
            <span>{activeTool ? `Running ${activeTool}…` : "Thinking…"}</span>
          </div>
        ) : (
          <div
            className={cn(
              "whitespace-pre-wrap break-words text-md text-ink",
              message.streaming && message.content && "streaming-caret"
            )}
          >
            {message.content}
          </div>
        )}

        {message.streaming && activeTool && message.content && (
          <p className="mt-2 text-xs text-ink-muted">Running {activeTool}…</p>
        )}

        {message.tools.map((tool, i) => (
          <ToolTrace key={`${tool.name}-${i}`} tool={tool} />
        ))}

        {message.error &&
          (() => {
            const notice = noticeFor(message.errorKind);
            const warning = notice.tone === "warning";
            return (
              <div
                // `status` rather than `alert` for the warning tone: a screen reader
                // should not interrupt to say the answer it is mid-way through reading
                // stopped early. A failure with nothing above it still interrupts.
                role={warning ? "status" : "alert"}
                data-error-kind={message.errorKind ?? "internal"}
                className={cn(
                  "mt-3 rounded-md border px-3 py-2 text-sm",
                  // The tone lives in the border and the fill, not the type. Amber text
                  // on an amber tint is 4.32:1 in the light theme — under AA, and the
                  // label is 14px medium, which does not qualify for the large-text
                  // exemption. The ink ramp clears 5:1 on both fills in both themes.
                  warning
                    ? "border-warning/40 bg-warning-subtle"
                    : "border-danger/40 bg-danger-subtle",
                )}
              >
                <p className="font-medium text-ink">{notice.label}</p>
                <p className="text-ink-secondary">{message.error}</p>
                {notice.hint && (
                  <p className="mt-1 text-xs text-ink-muted">{notice.hint}</p>
                )}
              </div>
            );
          })()}
      </div>
    </article>
  );
}

export function MessageList({
  messages,
  user,
  activeTool,
}: {
  messages: ChatMessage[];
  user: CurrentUser | null;
  activeTool: string | null;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);

  // Follow the stream only while the reader is already at the bottom. Yanking someone
  // back down while they are re-reading an earlier answer is the most irritating thing
  // a chat UI can do.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      pinnedToBottom.current = distance < 120;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (pinnedToBottom.current) {
      endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages]);

  return (
    <div
      ref={containerRef}
      data-thread=""
      className="scroll-region h-full overflow-y-auto"
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-7 px-4 py-6 sm:px-6">
        {messages.map((message) => (
          <MessageRow
            key={message.id}
            message={message}
            user={user}
            activeTool={message.streaming ? activeTool : null}
          />
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
