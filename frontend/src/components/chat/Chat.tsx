import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { API_BASE_URL, initialsFor, type CurrentUser } from "@/lib/config";

type ChartData = Record<string, unknown> | Array<Record<string, unknown>>;

/** A point in a `get_metric_trend` series. */
interface SeriesPoint {
  date: string;
  value: number;
}

/** One side of a `compare_segments` result. */
interface SegmentValue {
  name: string;
  value: number;
  customers?: number;
}

type MetricMeta = { metric?: string; label?: string; unit?: string; period?: string };
type TrendResult = MetricMeta & { series: SeriesPoint[] };
type CompareResult = MetricMeta & { segment_a: SegmentValue; segment_b: SegmentValue };
type RatioTerm = { metric: string; value: number };
type SnapshotResult = MetricMeta & {
  value: number;
  numerator?: RatioTerm;
  denominator?: RatioTerm;
};

function isSeriesResult(d: ChartData): d is TrendResult {
  return !Array.isArray(d) && Array.isArray((d as TrendResult).series);
}

function isCompareResult(d: ChartData): d is CompareResult {
  return !Array.isArray(d) && "segment_a" in d && "segment_b" in d;
}

function isSnapshotResult(d: ChartData): d is SnapshotResult {
  return !Array.isArray(d) && typeof (d as SnapshotResult).value === "number";
}

/** Currency metrics get a $ and thousands separators; ratios become percentages. */
function formatValue(value: number, unit?: string): string {
  if (unit === "currency_usd") {
    return value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  }
  if (unit === "ratio") return `${(value * 100).toFixed(2)}%`;
  return value.toLocaleString();
}

/** One tool the assistant ran, kept so every number stays traceable to its source. */
interface ToolInvocation {
  name: string;
  input?: Record<string, unknown>;
  data?: ChartData;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  /** A list, not a single slot: one turn can produce several parallel tool calls. */
  tools?: ToolInvocation[];
  isError?: boolean;
}

// Mirrors the typed SSE events emitted by stream_orchestrator (backend/app/streaming/sse.py).
type SseEvent =
  | { type: "token"; text: string }
  | { type: "tool_call"; name: string }
  | { type: "tool_result"; name: string; input?: Record<string, unknown>; data: ChartData }
  | { type: "usage"; input_tokens: number; output_tokens: number }
  | { type: "error"; message: string };

const STROKE = "#6366f1"; // indigo-500
const FILL = "#8b5cf6"; // violet-500
const AXIS = { stroke: "#94a3b8", fontSize: 12, tickLine: false } as const;
const TOOLTIP = {
  contentStyle: { backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "8px" },
  labelStyle: { color: "#f8fafc", fontWeight: "bold" },
} as const;

const ChartFrame = ({ children }: { children: React.ReactElement }) => (
  <div className="h-64 w-full mt-3 bg-slate-950/40 p-4 rounded-xl border border-slate-800">
    <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
  </div>
);

const ChartComponent = ({ data }: { data: ChartData }) => {
  if (!data) return null;

  // get_metric_trend -> { metric, label, unit, series: [{date, value}] }
  if (isSeriesResult(data) && data.series.length > 0) {
    const unit = data.unit;
    return (
      <ChartFrame>
        <LineChart data={data.series}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="date" {...AXIS} />
          <YAxis {...AXIS} tickFormatter={(v) => formatValue(Number(v), unit)} width={70} />
          <Tooltip {...TOOLTIP} formatter={(v) => formatValue(Number(v), unit)} />
          <Legend wrapperStyle={{ fontSize: "12px", paddingTop: "10px" }} />
          <Line
            type="monotone"
            dataKey="value"
            name={data.label ?? "value"}
            stroke={STROKE}
            strokeWidth={2}
            dot={{ r: 3, strokeWidth: 2 }}
            activeDot={{ r: 6 }}
          />
        </LineChart>
      </ChartFrame>
    );
  }

  // compare_segments -> { segment_a: {name, value}, segment_b: {name, value} }
  if (isCompareResult(data)) {
    const unit = data.unit;
    const rows = [data.segment_a, data.segment_b].map((s) => ({ name: s.name, value: s.value }));
    return (
      <ChartFrame>
        <BarChart data={rows}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="name" {...AXIS} />
          <YAxis {...AXIS} tickFormatter={(v) => formatValue(Number(v), unit)} width={70} />
          <Tooltip {...TOOLTIP} formatter={(v) => formatValue(Number(v), unit)} />
          <Legend wrapperStyle={{ fontSize: "12px", paddingTop: "10px" }} />
          <Bar dataKey="value" name={data.label ?? "value"} fill={FILL} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ChartFrame>
    );
  }

  // get_metric_value -> a single figure, shown with the terms behind it when it is a ratio.
  if (isSnapshotResult(data)) {
    const { numerator, denominator } = data;
    return (
      <div className="mt-3 p-4 bg-slate-950/40 rounded-xl border border-slate-800">
        <div className="text-[10px] uppercase tracking-wider text-slate-500">{data.label ?? data.metric}</div>
        <div className="text-2xl font-bold text-slate-100 mt-1">{formatValue(data.value, data.unit)}</div>
        {data.period && <div className="text-[10px] text-slate-500 mt-0.5">{String(data.period).replace(/_/g, " ")}</div>}
        {numerator && denominator && (
          <div className="text-[10px] text-slate-500 mt-2 font-mono">
            {numerator.value} {numerator.metric} / {denominator.value} {denominator.metric}
          </div>
        )}
      </div>
    );
  }

  // get_top_customers and anything else: show the rows as-is.
  if (Array.isArray(data) && data.length > 0) {
    return (
      <div className="mt-3 p-4 bg-slate-950/60 rounded-xl border border-slate-800 overflow-auto text-xs text-slate-300 font-mono max-h-60">
        <pre>{JSON.stringify(data, null, 2)}</pre>
      </div>
    );
  }

  return null;
};

/** Names the tool behind an answer and, on demand, shows the rows it returned. */
const ToolTrace = ({ tool }: { tool: ToolInvocation }) => {
  const [open, setOpen] = useState(false);
  const args = tool.input
    ? Object.entries(tool.input).map(([k, v]) => `${k}=${String(v)}`).join("  ")
    : "";

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex items-center gap-2 text-[10px] uppercase tracking-wider font-semibold text-slate-500 hover:text-indigo-400 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-indigo-500 rounded transition-colors"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-indigo-500" aria-hidden="true" />
        {tool.name}
        {args && <span className="normal-case tracking-normal font-normal text-slate-600">{args}</span>}
      </button>
      {open && tool.data !== undefined && (
        <div className="mt-2 p-3 bg-slate-950/60 rounded-lg border border-slate-800 overflow-auto text-[11px] text-slate-400 font-mono max-h-48">
          <pre>{JSON.stringify(tool.data, null, 2)}</pre>
        </div>
      )}
      {tool.data !== undefined && <ChartComponent data={tool.data} />}
    </div>
  );
};

const SUGGESTIONS = [
  { text: "What is my MRR for the last 6 months?", icon: "📈", desc: "View MRR trends" },
  { text: "What is my churn rate for last quarter?", icon: "🔄", desc: "Calculate lost accounts" },
  { text: "Compare active users for enterprise vs smb", icon: "👥", desc: "Analyze customer segments" },
  { text: "Who are my top 5 customers by MRR?", icon: "🏆", desc: "List highest paying users" },
  { text: "Show me active alerts", icon: "🔔", desc: "Scan billing & usage spikes" },
];

const CAPABILITIES = [
  { icon: "📈", title: "Trend Analysis", body: "MRR, ARR, active users and signups over time." },
  { icon: "🔄", title: "Churn Rate", body: "Cancellation rate by month, quarter or year." },
  { icon: "👥", title: "Segment Comparisons", body: "Side-by-side performance of customer segments." },
];

export function Chat({
  token,
  user,
  onLogout,
}: {
  token: string;
  user: CurrentUser | null;
  onLogout: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: "Hello! I am your AI Co-Pilot. How can I help you analyze your SaaS metrics today?" },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  /** Which tool is running right now. Held in state rather than smuggled into the
   *  message body as a "_Calling ..." sentinel string that then had to be parsed back out. */
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Abort any in-flight stream on unmount so the backend stops generating — and stops
  // billing — for a response nobody will read.
  useEffect(() => () => abortRef.current?.abort(), []);

  const updateLastMessage = useCallback((fn: (msg: Message) => Message) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      return [...prev.slice(0, -1), fn(prev[prev.length - 1])];
    });
  }, []);

  const submitQuery = useCallback(
    async (queryText: string) => {
      if (!queryText.trim() || loading) return;

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setMessages((prev) => [
        ...prev,
        { role: "user", content: queryText },
        { role: "assistant", content: "", tools: [] },
      ]);
      setLoading(true);
      setActiveTool(null);

      try {
        const response = await fetch(`${API_BASE_URL}/api/copilot/query`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ message: queryText }),
          signal: controller.signal,
        });

        if (!response.ok) {
          const detail =
            response.status === 400 ? "That request was blocked by the safety filter."
            : response.status === 401 ? "Your session expired. Please sign in again."
            : response.status === 429 ? "Rate limit reached. Wait a moment and try again."
            : `Request failed (${response.status}).`;
          updateLastMessage((msg) => ({ ...msg, content: detail, isError: true }));
          return;
        }

        const reader = response.body?.getReader();
        if (!reader) return;
        const decoder = new TextDecoder("utf-8");

        let buffer = "";
        streamLoop: while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const dataStr = line.slice("data: ".length).trim();
            if (dataStr === "[DONE]") break streamLoop;
            if (!dataStr) continue;

            let parsed: SseEvent;
            try {
              parsed = JSON.parse(dataStr) as SseEvent;
            } catch {
              continue; // partial chunk; the remainder stays in `buffer`
            }

            switch (parsed.type) {
              case "token":
                setActiveTool(null);
                updateLastMessage((msg) => ({ ...msg, content: msg.content + parsed.text }));
                break;
              case "tool_call":
                setActiveTool(parsed.name);
                break;
              case "tool_result":
                updateLastMessage((msg) => ({
                  ...msg,
                  tools: [...(msg.tools ?? []), { name: parsed.name, input: parsed.input, data: parsed.data }],
                }));
                break;
              case "error":
                updateLastMessage((msg) => ({ ...msg, content: parsed.message, isError: true }));
                break;
              case "usage":
                // No UI surface yet; available here for a future cost/usage display.
                break;
            }
          }
        }
      } catch (error) {
        if ((error as Error).name === "AbortError") return;
        console.error(error);
        updateLastMessage((msg) => ({ ...msg, content: "Could not reach the co-pilot.", isError: true }));
      } finally {
        setLoading(false);
        setActiveTool(null);
        abortRef.current = null;
      }
    },
    [loading, token, updateLastMessage]
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    submitQuery(text);
    setInput("");
  };

  const roleLabel = user?.role ? user.role[0].toUpperCase() + user.role.slice(1) : "";

  return (
    <div className="flex h-screen w-full bg-slate-950 text-slate-100 overflow-hidden relative">
      <div className="absolute top-10 left-10 h-72 w-72 rounded-full bg-indigo-500/10 blur-[120px] pointer-events-none" aria-hidden="true" />
      <div className="absolute bottom-10 right-10 h-80 w-80 rounded-full bg-violet-600/10 blur-[140px] pointer-events-none" aria-hidden="true" />

      {/* Left Sidebar */}
      <aside className="w-80 border-r border-slate-900 bg-slate-900/30 backdrop-blur-md flex-col justify-between shrink-0 hidden md:flex">
        <div className="p-6 flex-1 flex flex-col gap-6 overflow-y-auto">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-500 to-violet-500 text-white shadow-md shadow-indigo-500/10">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-5 h-5" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
              </svg>
            </div>
            <div>
              <h1 className="font-bold text-base tracking-wide bg-gradient-to-r from-indigo-200 to-slate-100 bg-clip-text text-transparent">Console Co-Pilot</h1>
              {roleLabel && (
                <span className="text-[10px] uppercase font-semibold tracking-wider text-slate-500">{roleLabel} access</span>
              )}
            </div>
          </div>

          <div className="space-y-3">
            <h2 className="text-[11px] uppercase font-bold tracking-wider text-slate-500">Query Capabilities</h2>
            <div className="space-y-2 text-xs text-slate-400">
              {CAPABILITIES.map((c) => (
                <div key={c.title} className="flex items-start gap-2.5 bg-slate-900/20 border border-slate-800/40 p-2.5 rounded-lg">
                  <span className="text-indigo-400 text-sm" aria-hidden="true">{c.icon}</span>
                  <div>
                    <div className="font-semibold text-slate-200">{c.title}</div>
                    <p className="text-[10px] text-slate-500 mt-0.5">{c.body}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <p className="text-[10px] text-slate-600 leading-relaxed border-t border-slate-900 pt-4">
            Every figure comes from a tool call scoped to your tenant. Expand the tool trace
            under any answer to see the arguments used and the rows returned.
          </p>
        </div>

        {/* Profile Footer */}
        <div className="p-4 border-t border-slate-900 bg-slate-950/20 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="h-8 w-8 shrink-0 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-xs font-bold text-slate-200">
              {initialsFor(user)}
            </div>
            <div className="min-w-0">
              <div className="text-xs font-semibold text-slate-200 truncate">{user?.email ?? "Loading…"}</div>
              <span className="text-[9px] text-slate-500 capitalize">{user?.role ?? ""}</span>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onLogout} aria-label="Sign out" className="text-slate-400 hover:text-slate-200 hover:bg-slate-900 rounded-lg h-8 w-8 p-0 shrink-0">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-4 h-4" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
            </svg>
          </Button>
        </div>
      </aside>

      {/* Main Panel */}
      <main className="flex-1 flex flex-col justify-between h-full bg-slate-900/10 backdrop-blur-sm min-w-0">
        <header className="h-16 border-b border-slate-900 bg-slate-950/30 px-4 sm:px-6 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-tr from-indigo-500 to-violet-500 text-white md:hidden shrink-0">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-4 h-4" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
              </svg>
            </div>
            <h1 className="font-bold text-sm tracking-wide text-slate-100 truncate">SaaS Co-Pilot</h1>
          </div>
          <Button variant="outline" size="sm" onClick={onLogout} className="border-slate-800 bg-slate-950/50 text-slate-300 hover:text-white md:hidden h-8 rounded-lg shrink-0">
            Sign out
          </Button>
        </header>

        <div className="flex-1 overflow-hidden relative">
          <ScrollArea className="h-full px-4 sm:px-6 py-6">
            <div className="max-w-3xl mx-auto flex flex-col gap-6 pb-20">
              {messages.length === 1 && (
                <div className="flex flex-col gap-6 py-8">
                  <div className="space-y-2 text-center max-w-lg mx-auto">
                    <h2 className="text-2xl font-extrabold tracking-tight bg-gradient-to-r from-indigo-200 via-slate-100 to-violet-200 bg-clip-text text-transparent">
                      AI SaaS Copilot Console
                    </h2>
                    <p className="text-slate-400 text-xs leading-relaxed">
                      Ask questions in plain English. Each question is mapped to a validated,
                      tenant-scoped query, and the tool call behind every answer is shown so
                      you can check the numbers rather than trust them.
                    </p>
                  </div>

                  <div className="space-y-3 mt-4">
                    <h3 className="text-[10px] uppercase font-bold tracking-widest text-slate-500 text-center">Suggested Analytics Queries</h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                      {SUGGESTIONS.map((s) => (
                        <button
                          key={s.text}
                          onClick={() => submitQuery(s.text)}
                          disabled={loading}
                          className="flex items-start gap-3 text-left p-3.5 rounded-xl border border-slate-800/80 bg-slate-900/30 hover:bg-slate-900/60 hover:border-indigo-500/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-50 transition-all group"
                        >
                          <span className="text-xl bg-slate-900 border border-slate-800 p-1.5 rounded-lg group-hover:scale-110 transition-transform" aria-hidden="true">{s.icon}</span>
                          <div>
                            <div className="text-xs font-semibold text-slate-200 group-hover:text-indigo-300 transition-colors">{s.text}</div>
                            <span className="text-[10px] text-slate-500 mt-0.5 block">{s.desc}</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {messages.length > 1 && messages.map((msg, i) => (
                <div key={i} className={`flex w-full ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div className={`flex gap-3 max-w-[85%] ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}>
                    <div
                      className={`h-8 w-8 rounded-full border shrink-0 flex items-center justify-center text-xs font-bold ${
                        msg.role === "user"
                          ? "bg-indigo-600 border-indigo-500 text-white shadow-lg shadow-indigo-600/10"
                          : "bg-slate-800 border-slate-700 text-indigo-400"
                      }`}
                      aria-hidden="true"
                    >
                      {msg.role === "user" ? initialsFor(user) : "AI"}
                    </div>

                    <div
                      className={`rounded-2xl px-4 py-3 text-[14px] leading-relaxed shadow-sm min-w-0 ${
                        msg.role === "user"
                          ? "bg-indigo-600 text-slate-100 rounded-tr-none"
                          : msg.isError
                            ? "bg-red-500/10 border border-red-500/30 text-red-300 rounded-tl-none"
                            : "bg-slate-900/40 border border-slate-800/80 text-slate-200 rounded-tl-none backdrop-blur-sm"
                      }`}
                      {...(msg.isError ? { role: "alert" } : {})}
                    >
                      <div className="whitespace-pre-wrap break-words">{msg.content}</div>
                      {msg.tools?.map((tool, ti) => <ToolTrace key={ti} tool={tool} />)}
                    </div>
                  </div>
                </div>
              ))}

              {loading && (
                <div className="flex justify-start">
                  <div className="flex gap-3 max-w-[85%] items-center">
                    <div className="h-8 w-8 rounded-full border bg-slate-800 border-slate-700 text-indigo-400 flex items-center justify-center text-xs font-bold" aria-hidden="true">AI</div>
                    <div className="rounded-2xl rounded-tl-none px-4 py-3 border border-slate-800 bg-slate-900/40 backdrop-blur-sm text-slate-400 text-xs flex items-center gap-2">
                      <svg className="animate-spin h-4 w-4 text-indigo-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                      </svg>
                      {activeTool ? `Running ${activeTool}…` : "Thinking…"}
                    </div>
                  </div>
                </div>
              )}

              {/* Announces progress to assistive tech without moving focus. */}
              <div aria-live="polite" className="sr-only">
                {loading ? (activeTool ? `Running ${activeTool}` : "Thinking") : ""}
              </div>

              <div ref={scrollRef} />
            </div>
          </ScrollArea>
        </div>

        <footer className="p-4 border-t border-slate-900 bg-slate-950/30 backdrop-blur-md shrink-0">
          <div className="max-w-3xl mx-auto">
            <form onSubmit={handleSubmit} className="flex w-full items-center gap-2">
              <label htmlFor="copilot-input" className="sr-only">Ask about your metrics</label>
              <Input
                id="copilot-input"
                type="text"
                placeholder="Ask about your metrics… (e.g. 'What is my MRR for the last 6 months?')"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={loading}
                className="flex-1 h-12 text-sm rounded-xl bg-slate-950/80 border-slate-800/80 text-slate-200 placeholder-slate-500 focus-visible:ring-indigo-500 focus-visible:border-indigo-500"
              />
              <Button
                type="submit"
                disabled={loading || !input.trim()}
                className="h-12 px-5 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 hover:from-indigo-600 hover:to-violet-600 text-white font-semibold shadow-lg shadow-indigo-500/20 hover:shadow-indigo-500/30 transition-all"
              >
                Send
              </Button>
            </form>
          </div>
        </footer>
      </main>
    </div>
  );
}
