import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

interface Message {
  role: "user" | "assistant";
  content: string;
  chartData?: any;
  toolName?: string;
}

const ChartComponent = ({ data, toolName }: { data: any, toolName: string }) => {
  if (!data) return null;

  if (toolName === "compare_segments" && typeof data === "dict" || !Array.isArray(data)) {
    // Convert dict to array for BarChart
    const arrData = Object.entries(data).map(([key, value]) => ({ name: key, value }));
    return (
      <div className="h-64 w-full mt-4">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={arrData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" />
            <YAxis />
            <Tooltip />
            <Legend />
            <Bar dataKey="value" fill="#8884d8" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (Array.isArray(data) && data.length > 0 && data[0].date !== undefined) {
    return (
      <div className="h-64 w-full mt-4">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="value" stroke="#8884d8" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }
  
  if (Array.isArray(data)) {
    return (
      <div className="mt-4 p-2 bg-white rounded border overflow-auto text-xs text-black">
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = input.trim();
    setMessages(prev => [...prev, { role: "user", content: userMessage }]);
    setInput("");
    setLoading(true);

    try {
      const response = await fetch(`${apiUrl}/api/copilot/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ message: userMessage })
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
                      lastMessage.content += parsed.content;
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
                  }
                } catch (err) {
                  // Ignore parse errors from partial chunks if any
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

  return (
    <div className="flex h-screen w-full items-center justify-center bg-gray-50 p-4">
      <Card className="w-full max-w-4xl h-[80vh] flex flex-col shadow-xl">
        <CardHeader className="flex flex-row items-center justify-between border-b px-6 py-4">
          <CardTitle className="text-xl font-semibold">SaaS Analytics Co-Pilot</CardTitle>
          <Button variant="outline" size="sm" onClick={onLogout}>Logout</Button>
        </CardHeader>
        <CardContent className="flex-1 overflow-hidden p-0 bg-gray-50">
          <ScrollArea className="h-full px-6 py-4">
            <div className="flex flex-col gap-6 pb-4">
              {messages.map((msg, i) => (
                <div key={i} className={`flex w-max max-w-[85%] flex-col gap-2 rounded-lg px-5 py-4 text-[15px] shadow-sm ${msg.role === 'user' ? 'ml-auto bg-blue-600 text-white' : 'bg-white border border-gray-100 text-gray-800'}`}>
                  <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
                  {msg.chartData && <ChartComponent data={msg.chartData} toolName={msg.toolName || ""} />}
                </div>
              ))}
              <div ref={scrollRef} />
            </div>
          </ScrollArea>
        </CardContent>
        <CardFooter className="border-t p-4 bg-white">
          <form onSubmit={handleSubmit} className="flex w-full items-center space-x-3">
            <Input 
              type="text" 
              placeholder="Ask about your metrics... (e.g. 'What is my MRR?' or 'Compare segments enterprise and smb')" 
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading}
              className="flex-1 h-12 text-base rounded-full px-6 bg-gray-50 border-gray-200 focus-visible:ring-blue-500"
            />
            <Button type="submit" disabled={loading || !input.trim()} className="h-12 px-6 rounded-full bg-blue-600 hover:bg-blue-700 transition-colors">
              {loading ? "Thinking..." : "Send"}
            </Button>
          </form>
        </CardFooter>
      </Card>
    </div>
  );
}
