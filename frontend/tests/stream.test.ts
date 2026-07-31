/**
 * The SSE stream parser.
 *
 * This is the riskiest logic in the client: it reassembles events from arbitrary byte
 * chunk boundaries, and every bug in it looks like "the assistant stopped mid-sentence".
 * The original implementation broke out of the inner loop on [DONE] but never exited the
 * outer one, and only terminated because the socket happened to close.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";

import { ApiError, streamQuery, type StreamEvent } from "@/lib/api";

/** Build a Response whose body streams the given chunks as-is. */
function sseResponse(chunks: string[], init: ResponseInit = {}) {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "X-Conversation-Id": "conv_abc", ...(init.headers ?? {}) },
    ...init,
  });
}

async function collect(chunks: string[]): Promise<StreamEvent[]> {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(sseResponse(chunks))
  );
  const handle = { conversationId: null as string | null };
  const events: StreamEvent[] = [];
  for await (const event of streamQuery(
    "token",
    "question",
    null,
    new AbortController().signal,
    handle
  )) {
    events.push(event);
  }
  return events;
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("streamQuery", () => {
  it("decodes one event per data line", async () => {
    const events = await collect([
      'data: {"type":"token","text":"Your MRR "}\n\n',
      'data: {"type":"token","text":"is 5600."}\n\n',
      "data: [DONE]\n\n",
    ]);
    expect(events).toEqual([
      { type: "token", text: "Your MRR " },
      { type: "token", text: "is 5600." },
    ]);
  });

  it("reassembles an event split across chunk boundaries", async () => {
    // A network chunk can end mid-JSON; the remainder must be buffered, not dropped.
    const events = await collect([
      'data: {"type":"token","tex',
      't":"split across chunks"}\n\n',
      "data: [DONE]\n\n",
    ]);
    expect(events).toEqual([{ type: "token", text: "split across chunks" }]);
  });

  it("reassembles an event split mid-delimiter", async () => {
    const events = await collect([
      'data: {"type":"token","text":"a"}\n',
      '\ndata: {"type":"token","text":"b"}\n\n',
      "data: [DONE]\n\n",
    ]);
    expect(events.map((e) => (e as { text: string }).text)).toEqual(["a", "b"]);
  });

  it("stops at [DONE] and ignores anything after it", async () => {
    // Regression: [DONE] used to break only the inner loop.
    const events = await collect([
      'data: {"type":"token","text":"before"}\n\n',
      "data: [DONE]\n\n",
      'data: {"type":"token","text":"after — must not appear"}\n\n',
    ]);
    expect(events).toHaveLength(1);
    expect((events[0] as { text: string }).text).toBe("before");
  });

  it("skips malformed JSON rather than aborting the stream", async () => {
    const events = await collect([
      "data: {not json at all}\n\n",
      'data: {"type":"token","text":"still delivered"}\n\n',
      "data: [DONE]\n\n",
    ]);
    expect(events).toEqual([{ type: "token", text: "still delivered" }]);
  });

  it("ignores lines that are not data frames", async () => {
    const events = await collect([
      ": heartbeat comment\n\n",
      "event: ping\n\n",
      'data: {"type":"token","text":"ok"}\n\n',
      "data: [DONE]\n\n",
    ]);
    expect(events).toEqual([{ type: "token", text: "ok" }]);
  });

  it("carries tool results through intact", async () => {
    const payload = {
      type: "tool_result",
      name: "get_metric_trend",
      input: { metric: "mrr" },
      data: { series: [{ date: "2026-01", value: 100 }] },
    };
    const events = await collect([
      `data: ${JSON.stringify(payload)}\n\n`,
      "data: [DONE]\n\n",
    ]);
    expect(events[0]).toEqual(payload);
  });

  it("adopts the conversation id the server reports", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(sseResponse(["data: [DONE]\n\n"]))
    );
    const handle = { conversationId: null as string | null };
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    for await (const _ of streamQuery(
      "t",
      "q",
      null,
      new AbortController().signal,
      handle
    )) {
      /* drain */
    }
    expect(handle.conversationId).toBe("conv_abc");
  });

  it("throws a typed ApiError carrying the status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Daily usage limit reached." }), {
          status: 429,
        })
      )
    );
    const handle = { conversationId: null as string | null };
    const iterate = async () => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      for await (const _ of streamQuery(
        "t",
        "q",
        null,
        new AbortController().signal,
        handle
      )) {
        /* not reached */
      }
    };
    await expect(iterate()).rejects.toBeInstanceOf(ApiError);
    await expect(iterate()).rejects.toMatchObject({ status: 429 });
  });
});

describe("ApiError.friendlyMessage", () => {
  it("maps each status to something a user can act on", () => {
    expect(new ApiError(401, "").friendlyMessage).toMatch(/sign in/i);
    expect(new ApiError(403, "").friendlyMessage).toMatch(/role/i);
    expect(new ApiError(404, "").friendlyMessage).toMatch(/no longer exists/i);
    expect(new ApiError(500, "").friendlyMessage).toMatch(/went wrong/i);
  });

  it("prefers the server's own message where it is specific", () => {
    expect(new ApiError(429, "Daily usage limit reached.").friendlyMessage).toBe(
      "Daily usage limit reached."
    );
  });
});
