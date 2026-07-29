/**
 * Typed API client.
 *
 * One place that knows the base URL, how a token is attached, and how the server
 * reports an error. Components call these functions; none of them build a fetch.
 */

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:6001";

export interface CurrentUser {
  id: string;
  email: string;
  role: "viewer" | "analyst" | "admin";
  tenant_id: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string | null;
  updated_at: string | null;
  message_count: number;
}

export interface ToolInvocation {
  name: string;
  input?: Record<string, unknown>;
  data?: unknown;
}

export interface StoredMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: ToolInvocation[];
  created_at: string | null;
}

export interface ConversationDetail extends ConversationSummary {
  messages: StoredMessage[];
}

/** An error carrying the HTTP status, so callers can distinguish 401 from 429. */
export class ApiError extends Error {
  // Declared as a field rather than a constructor parameter property: the project
  // compiles with `erasableSyntaxOnly`, which disallows the shorthand.
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }

  /** A message safe and useful to show a user. */
  get friendlyMessage(): string {
    switch (this.status) {
      case 401:
        return "Your session expired. Please sign in again.";
      case 403:
        return "Your role does not allow that.";
      case 404:
        return "That conversation no longer exists.";
      case 429:
        return this.message || "Rate limit reached. Wait a moment and try again.";
      case 400:
        return this.message || "That request was rejected.";
      default:
        return this.message || "Something went wrong. Try again.";
    }
  }
}

async function request<T>(
  path: string,
  token: string | null,
  init: RequestInit = {}
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail = typeof body?.detail === "string" ? body.detail : "";
    } catch {
      /* a non-JSON error body is not worth surfacing */
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; expires_in: number }>("/api/auth/login", null, {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  logout: () => request<unknown>("/api/auth/logout", null, { method: "POST" }),

  refresh: () =>
    request<{ access_token: string; expires_in: number }>("/api/auth/refresh", null, {
      method: "POST",
    }),

  me: (token: string) => request<CurrentUser>("/api/auth/me", token),

  listConversations: (token: string) =>
    request<ConversationSummary[]>("/api/conversations", token),

  getConversation: (token: string, id: string) =>
    request<ConversationDetail>(`/api/conversations/${id}`, token),

  renameConversation: (token: string, id: string, title: string) =>
    request<ConversationSummary>(`/api/conversations/${id}`, token, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  deleteConversation: (token: string, id: string) =>
    request<void>(`/api/conversations/${id}`, token, { method: "DELETE" }),
};

// ---------------------------------------------------------------------------
// Streaming
// ---------------------------------------------------------------------------

export type StreamEvent =
  | { type: "token"; text: string }
  | { type: "tool_call"; name: string }
  | { type: "tool_result"; name: string; input?: Record<string, unknown>; data: unknown }
  | { type: "usage"; input_tokens: number; output_tokens: number }
  | { type: "error"; message: string };

export interface StreamHandle {
  conversationId: string | null;
}

/**
 * POST a question and yield decoded SSE events.
 *
 * Written as an async generator so the caller drives it with `for await`, and
 * cancellation is just aborting the signal — no callback soup, no leaked reader.
 */
export async function* streamQuery(
  token: string,
  message: string,
  conversationId: string | null,
  signal: AbortSignal,
  handle: StreamHandle
): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${API_BASE_URL}/api/copilot/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    credentials: "include",
    signal,
  });

  if (!response.ok) {
    let detail = "";
    try {
      detail = (await response.json())?.detail ?? "";
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, detail);
  }

  // The server reports which conversation this turn belongs to, so a first message
  // can create one without the client having to guess an id.
  handle.conversationId =
    response.headers.get("X-Conversation-Id") ?? conversationId ?? null;

  const reader = response.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    // The trailing fragment may be an incomplete line; keep it for the next chunk.
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6).trim();
      if (!payload) continue;
      if (payload === "[DONE]") return;
      try {
        yield JSON.parse(payload) as StreamEvent;
      } catch {
        /* a partial chunk; the remainder is still in `buffer` */
      }
    }
  }
}
