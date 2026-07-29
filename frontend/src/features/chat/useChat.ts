import { useCallback, useEffect, useRef, useState } from "react";

import type { ChatMessage } from "@/features/chat/MessageList";
import { ApiError, streamQuery, type StreamHandle } from "@/lib/api";

let counter = 0;
const nextId = () => `m${++counter}`;

/**
 * Chat state for one conversation.
 *
 * Owns the stream lifecycle: starting a turn aborts any previous one, unmounting
 * aborts the current one, and every state update is immutable so React's concurrent
 * rendering cannot observe a half-applied message.
 */
export function useChat({
  token,
  conversationId,
  onConversationCreated,
  onTurnComplete,
  onAuthExpired,
}: {
  token: string;
  conversationId: string | null;
  onConversationCreated: (id: string) => void;
  onTurnComplete: () => void;
  onAuthExpired: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const patchLast = useCallback((patch: (m: ChatMessage) => ChatMessage) => {
    setMessages((prev) =>
      prev.length === 0 ? prev : [...prev.slice(0, -1), patch(prev[prev.length - 1])]
    );
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    setActiveTool(null);
    patchLast((m) => ({
      ...m,
      streaming: false,
      content: m.content || "Stopped.",
    }));
  }, [patchLast]);

  const send = useCallback(
    async (text: string) => {
      if (busy) return;

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "user", content: text, tools: [] },
        { id: nextId(), role: "assistant", content: "", tools: [], streaming: true },
      ]);
      setBusy(true);
      setActiveTool(null);

      const handle: StreamHandle = { conversationId };

      try {
        for await (const event of streamQuery(
          token,
          text,
          conversationId,
          controller.signal,
          handle
        )) {
          switch (event.type) {
            case "token":
              setActiveTool(null);
              patchLast((m) => ({ ...m, content: m.content + event.text }));
              break;
            case "tool_call":
              setActiveTool(event.name);
              break;
            case "tool_result":
              patchLast((m) => ({
                ...m,
                tools: [
                  ...m.tools,
                  { name: event.name, input: event.input, data: event.data },
                ],
              }));
              break;
            case "error":
              patchLast((m) => ({ ...m, error: event.message }));
              break;
            case "usage":
              break; // no UI surface yet
          }
        }

        // A first message creates the conversation server-side; adopt its id so the
        // next turn continues the same thread.
        if (handle.conversationId && handle.conversationId !== conversationId) {
          onConversationCreated(handle.conversationId);
        }
        onTurnComplete();
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        if (err instanceof ApiError && err.status === 401) {
          onAuthExpired();
          return;
        }
        patchLast((m) => ({
          ...m,
          error:
            err instanceof ApiError
              ? err.friendlyMessage
              : "Could not reach the co-pilot.",
        }));
      } finally {
        setBusy(false);
        setActiveTool(null);
        abortRef.current = null;
        patchLast((m) => ({ ...m, streaming: false }));
      }
    },
    [
      busy,
      conversationId,
      onAuthExpired,
      onConversationCreated,
      onTurnComplete,
      patchLast,
      token,
    ]
  );

  return { messages, setMessages, busy, activeTool, send, cancel };
}
