import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

interface Message {
  role: "user" | "assistant";
  content: string;
  chartData?: Record<string, unknown> | Array<Record<string, unknown>>;
  toolName?: string;
}

const ChartComponent = ({ data, toolName }: { data: Record<string, unknown> | Array<Record<string, unknown>>, toolName: string }) => {
  if (!data) return null;

  // Custom styling tokens
  const strokeColor = "#6366f1"; // Indigo-500
  const fillColor = "#8b5cf6"; // Violet-500

  if (toolName === "compare_segments" && typeof data === "object" && !Array.isArray(data)) {
    const arrData = Object.entries(data).map(([key, value]) => ({ name: key, value }));
    return (
      <div className="h-64 w-full mt-4 bg-slate-950/40 p-4 rounded-xl border border-slate-800">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={arrData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="name" stroke="#94a3b8" fontSize={12} tickLine={false} />
            <YAxis stroke="#94a3b8" fontSize={12} tickLine={false} />
            <Tooltip 
              contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
              labelStyle={{ color: "#f8fafc", fontWeight: "bold" }}
            />
            <Legend wrapperStyle={{ fontSize: "12px", paddingTop: "10px" }} />
            <Bar dataKey="value" fill={fillColor} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (Array.isArray(data) && data.length > 0 && data[0].date !== undefined) {
    return (
      <div className="h-64 w-full mt-4 bg-slate-950/40 p-4 rounded-xl border border-slate-800">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} tickLine={false} />
            <YAxis stroke="#94a3b8" fontSize={12} tickLine={false} />
            <Tooltip 
              contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
              labelStyle={{ color: "#f8fafc", fontWeight: "bold" }}
            />
            <Legend wrapperStyle={{ fontSize: "12px", paddingTop: "10px" }} />
            <Line type="monotone" dataKey="value" stroke={strokeColor} strokeWidth={2} dot={{ r: 4, strokeWidth: 2 }} activeDot={{ r: 6 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }
  
  if (Array.isArray(data)) {
    return (
      <div className="mt-4 p-4 bg-slate-950/60 rounded-xl border border-slate-800 overflow-auto text-xs text-slate-300 font-mono max-h-60">
        <pre>{JSON.stringify(data, null, 2)}</pre>
      </div>
    );
  }

  return null;
};

export function Chat({ token, onLogout }: { token: string; onLogout: () => void }) {
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: "Hello! I am your AI Co-Pilot. How can I help you analyze your SaaS metrics today?" }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const apiUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:6001";

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const submitQuery = async (queryText: string) => {
    if (!queryText.trim() || loading) return;

    setMessages(prev => [...prev, { role: "user", content: queryText }]);
    setLoading(true);

    try {
      const response = await fetch(`${apiUrl}/api/copilot/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ message: queryText })
      });

      if (!response.ok) {
        throw new Error("Failed to send message");
      }

      setMessages(prev => [...prev, { role: "assistant", content: "" }]);
      
      const reader = response.body?.getReader();
      const decoder = new TextDecoder("utf-8");

      if (reader) {
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const dataStr = line.replace("data: ", "").trim();
              if (dataStr === "[DONE]") {
                break;
              }
              if (dataStr) {
                try {
                  const parsed = JSON.parse(dataStr);
                  
                  if (parsed.content) {
                    setMessages(prev => {
                      const newMessages = [...prev];
                      const lastMessage = newMessages[newMessages.length - 1];
                      lastMessage.content = lastMessage.content.startsWith('_Calling')
                        ? parsed.content
                        : lastMessage.content + parsed.content;
                      return newMessages;
                    });
                  } else if (parsed.chart_data) {
                    setMessages(prev => {
                      const newMessages = [...prev];
                      const lastMessage = newMessages[newMessages.length - 1];
                      lastMessage.chartData = parsed.chart_data;
                      lastMessage.toolName = parsed.tool_name;
                      return newMessages;
                    });
                  } else if (parsed.tool_call) {
                    setMessages(prev => {
                      const newMessages = [...prev];
                      const lastMessage = newMessages[newMessages.length - 1];
                      lastMessage.content = `_Calling ${parsed.tool_call}..._`;
                      return newMessages;
                    });
                  }
                } catch {
                  // Ignore parse errors from partial chunks
                }
              }
            }
          }
        }
      }
    } catch (error) {
      console.error(error);
      setMessages(prev => [...prev, { role: "assistant", content: "Error connecting to the co-pilot." }]);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;
    submitQuery(input);
    setInput("");
  };

  const handleSuggestionClick = (suggestion: string) => {
    if (loading) return;
    submitQuery(suggestion);
  };

  const suggestions = [
    { text: "What is my MRR for the last 6 months?", icon: "📈", desc: "View MRR trends" },
    { text: "What is my churn rate for last quarter?", icon: "🔄", desc: "Calculate lost accounts" },
    { text: "Compare active users for enterprise vs smb", icon: "👥", desc: "Analyze customer segments" },
    { text: "Who are my top 5 customers by MRR?", icon: "🏆", desc: "List highest paying users" },
    { text: "Show me active alerts", icon: "🔔", desc: "Scan billing & usage spikes" }
  ];

  return (
    <div className="flex h-screen w-full bg-slate-950 text-slate-100 overflow-hidden relative">
      {/* Dynamic Background Glows */}
      <div className="absolute top-10 left-10 h-72 w-72 rounded-full bg-indigo-500/10 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-10 right-10 h-80 w-80 rounded-full bg-violet-600/10 blur-[140px] pointer-events-none" />

      {/* Left Sidebar */}
      <aside className="w-80 border-r border-slate-900 bg-slate-900/30 backdrop-blur-md flex flex-col justify-between shrink-0 hidden md:flex">
        <div className="p-6 flex-1 flex flex-col gap-6 overflow-y-auto">
          {/* Logo Brand */}
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-500 to-violet-500 text-white shadow-md shadow-indigo-500/10">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-5 h-5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
              </svg>
            </div>
            <div>
              <h1 className="font-bold text-base tracking-wide bg-gradient-to-r from-indigo-200 to-slate-100 bg-clip-text text-transparent">Console Co-Pilot</h1>
              <span className="text-[10px] uppercase font-semibold tracking-wider text-slate-500 flex items-center gap-1">
                <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" /> Active DB Connected
              </span>
            </div>
          </div>

          {/* Quick Metrics Panel */}
          <div className="space-y-3">
            <h2 className="text-[11px] uppercase font-bold tracking-wider text-slate-500">Live Metrics Overview</h2>
            <div className="grid grid-cols-2 gap-2">
              <Card className="bg-slate-900/50 border-slate-800/80 p-3 rounded-xl">
                <span className="text-[10px] text-slate-400 font-medium">Est. MRR</span>
                <div className="text-sm font-bold text-slate-100 mt-0.5">$48,250</div>
                <span className="text-[9px] text-emerald-400 flex items-center gap-0.5 mt-0.5 font-medium">↑ 4.2%</span>
              </Card>
              <Card className="bg-slate-900/50 border-slate-800/80 p-3 rounded-xl">
                <span className="text-[10px] text-slate-400 font-medium">Churn Rate</span>
                <div className="text-sm font-bold text-slate-100 mt-0.5">2.1%</div>
                <span className="text-[9px] text-emerald-400 flex items-center gap-0.5 mt-0.5 font-medium">↓ Stable</span>
              </Card>
              <Card className="bg-slate-900/50 border-slate-800/80 p-3 rounded-xl">
                <span className="text-[10px] text-slate-400 font-medium">Avg ARPU</span>
                <div className="text-sm font-bold text-slate-100 mt-0.5">$120</div>
                <span className="text-[9px] text-indigo-400 flex items-center gap-0.5 mt-0.5 font-medium">↑ 1.8%</span>
              </Card>
              <Card className="bg-slate-900/50 border-slate-800/80 p-3 rounded-xl">
                <span className="text-[10px] text-slate-400 font-medium">Active Cust</span>
                <div className="text-sm font-bold text-slate-100 mt-0.5">1,240</div>
                <span className="text-[9px] text-emerald-400 flex items-center gap-0.5 mt-0.5 font-medium">↑ 12%</span>
              </Card>
            </div>
          </div>

          {/* Capabilities Guide */}
          <div className="space-y-3">
            <h2 className="text-[11px] uppercase font-bold tracking-wider text-slate-500">Query Capabilities</h2>
            <div className="space-y-2 text-xs text-slate-400">
              <div className="flex items-start gap-2.5 bg-slate-900/20 border border-slate-800/40 p-2.5 rounded-lg">
                <span className="text-indigo-400 text-sm">📈</span>
                <div>
                  <div className="font-semibold text-slate-200">Trend Analysis</div>
                  <p className="text-[10px] text-slate-500 mt-0.5">MRR, ARR, Active Users & signups over time.</p>
                </div>
              </div>
              <div className="flex items-start gap-2.5 bg-slate-900/20 border border-slate-800/40 p-2.5 rounded-lg">
                <span className="text-indigo-400 text-sm">🔄</span>
                <div>
                  <div className="font-semibold text-slate-200">Churn Rate</div>
                  <p className="text-[10px] text-slate-500 mt-0.5">Percentage of cancellations by month, quarter, or year.</p>
                </div>
              </div>
              <div className="flex items-start gap-2.5 bg-slate-900/20 border border-slate-800/40 p-2.5 rounded-lg">
                <span className="text-indigo-400 text-sm">👥</span>
                <div>
                  <div className="font-semibold text-slate-200">Segment Comparisons</div>
                  <p className="text-[10px] text-slate-500 mt-0.5">Side-by-side performance of user segments.</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Profile Footer */}
        <div className="p-4 border-t border-slate-900 bg-slate-950/20 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-xs font-bold text-slate-200">
              AD
            </div>
            <div>
              <div className="text-xs font-semibold text-slate-200">Admin User</div>
              <span className="text-[9px] text-slate-500">Workspace owner</span>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onLogout} className="text-slate-400 hover:text-slate-200 hover:bg-slate-900 rounded-lg h-8 w-8 p-0">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-4 h-4">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
            </svg>
          </Button>
        </div>
      </aside>

      {/* Main Panel */}
      <main className="flex-1 flex flex-col justify-between h-full bg-slate-900/10 backdrop-blur-sm">
        {/* Header (Mobile version header + actions) */}
        <header className="h-16 border-b border-slate-900 bg-slate-950/30 px-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-tr from-indigo-500 to-violet-500 text-white md:hidden">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-4 h-4">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
              </svg>
            </div>
            <h1 className="font-bold text-sm tracking-wide text-slate-100 flex items-center gap-2">
              SaaS Co-Pilot Interface <span className="text-[10px] bg-indigo-500/20 text-indigo-400 font-semibold px-2 py-0.5 rounded-full border border-indigo-500/30">AI Live</span>
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={onLogout} className="border-slate-800 bg-slate-950/50 text-slate-300 hover:text-white md:hidden h-8 rounded-lg">
              Logout
            </Button>
          </div>
        </header>

        {/* Chat area */}
        <div className="flex-1 overflow-hidden relative">
          <ScrollArea className="h-full px-6 py-6">
            <div className="max-w-3xl mx-auto flex flex-col gap-6 pb-20">
              
              {messages.length === 1 && (
                <div className="flex flex-col gap-6 py-8">
                  {/* Dashboard Onboarding Welcome Header */}
                  <div className="space-y-2 text-center max-w-lg mx-auto">
                    <h2 className="text-2xl font-extrabold tracking-tight bg-gradient-to-r from-indigo-200 via-slate-100 to-violet-200 bg-clip-text text-transparent">
                      AI SaaS Copilot Console
                    </h2>
                    <p className="text-slate-400 text-xs leading-relaxed">
                      Ask questions in plain English. The co-pilot maps your query to real-time functions, executes them against the seed database, and renders interactive charts.
                    </p>
                  </div>

                  {/* Suggestion Prompt Cards */}
                  <div className="space-y-3 mt-4">
                    <h3 className="text-[10px] uppercase font-bold tracking-widest text-slate-500 text-center">Suggested Analytics Queries</h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                      {suggestions.map((s, idx) => (
                        <button
                          key={idx}
                          onClick={() => handleSuggestionClick(s.text)}
                          className="flex items-start gap-3 text-left p-3.5 rounded-xl border border-slate-800/80 bg-slate-900/30 hover:bg-slate-900/60 hover:border-indigo-500/30 transition-all group pointer-events-auto"
                        >
                          <span className="text-xl bg-slate-900 border border-slate-800 p-1.5 rounded-lg group-hover:scale-110 transition-transform">{s.icon}</span>
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
                <div key={i} className={`flex w-full ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`flex gap-3 max-w-[85%] ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                    {/* User or Assistant Indicator */}
                    <div className={`h-8 w-8 rounded-full border shrink-0 flex items-center justify-center text-xs font-bold ${
                      msg.role === 'user' 
                        ? 'bg-indigo-600 border-indigo-500 text-white shadow-lg shadow-indigo-600/10' 
                        : 'bg-slate-850 border-slate-850 text-indigo-400'
                    }`}>
                      {msg.role === 'user' ? 'U' : 'AI'}
                    </div>

                    <div className={`flex flex-col gap-1`}>
                      <div className={`rounded-2xl px-4 py-3 text-[14px] leading-relaxed shadow-sm ${
                        msg.role === 'user' 
                          ? 'bg-indigo-600 text-slate-100 rounded-tr-none' 
                          : 'bg-slate-900/40 border border-slate-800/80 text-slate-200 rounded-tl-none backdrop-blur-sm'
                      }`}>
                        <div className="whitespace-pre-wrap">{msg.content}</div>
                        {msg.chartData && <ChartComponent data={msg.chartData} toolName={msg.toolName || ""} />}
                      </div>
                    </div>
                  </div>
                </div>
              ))}

              {/* Thinking/Loading Indicator */}
              {loading && (
                <div className="flex justify-start">
                  <div className="flex gap-3 max-w-[85%] items-center">
                    <div className="h-8 w-8 rounded-full border bg-slate-850 border-slate-850 text-indigo-400 flex items-center justify-center text-xs font-bold">
                      AI
                    </div>
                    <div className="rounded-2xl rounded-tl-none px-4 py-3 border border-slate-800 bg-slate-900/40 backdrop-blur-sm text-slate-400 text-xs flex items-center gap-2">
                      <svg className="animate-spin h-4 w-4 text-indigo-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      Thinking and query validating...
                    </div>
                  </div>
                </div>
              )}
              
              <div ref={scrollRef} />
            </div>
          </ScrollArea>
        </div>

        {/* Input area */}
        <footer className="p-4 border-t border-slate-900 bg-slate-950/30 backdrop-blur-md">
          <div className="max-w-3xl mx-auto">
            <form onSubmit={handleSubmit} className="flex w-full items-center gap-2">
              <Input 
                type="text" 
                placeholder="Ask about your metrics... (e.g. 'What is my MRR for the last 6 months?')" 
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
