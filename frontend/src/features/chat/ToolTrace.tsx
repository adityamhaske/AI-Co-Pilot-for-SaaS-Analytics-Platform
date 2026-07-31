import { Suspense, lazy, useState } from "react";

import { ChevronIcon, ToolIcon } from "@/components/ui/icons";
import { Skeleton } from "@/components/ui/primitives";
import type { ChartData } from "@/features/chart/ResultChart";
import type { ToolInvocation } from "@/lib/api";
import { cn } from "@/lib/utils";

// Recharts and its d3 dependencies are the bulk of the bundle and are only needed once
// an answer contains a figure. Loading them lazily keeps them off the login page and the
// first paint; the chunk arrives while the answer is still streaming.
const ResultChart = lazy(() =>
  import("@/features/chart/ResultChart").then((m) => ({ default: m.ResultChart }))
);

/**
 * Provenance for an answer.
 *
 * Nobody should take a number from a language model on trust, so every figure is
 * shown with the tool that produced it, the arguments it was called with, and — on
 * request — the rows it returned. This is the difference between a chatbot and
 * something an analyst will actually use.
 */

function describeArgs(input?: Record<string, unknown>): string {
  if (!input) return "";
  return Object.entries(input)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join(" · ");
}

export function ToolTrace({ tool }: { tool: ToolInvocation }) {
  const [showRaw, setShowRaw] = useState(false);
  const args = describeArgs(tool.input);

  return (
    <div className="mt-3">
      {tool.data !== undefined && (
        <Suspense fallback={<Skeleton className="mt-3 h-56 w-full rounded-lg" />}>
          <ResultChart data={tool.data as ChartData} />
        </Suspense>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="inline-flex items-center gap-1.5 text-2xs font-medium text-ink-muted">
          <ToolIcon className="h-3.5 w-3.5" />
          <code className="font-mono">{tool.name}</code>
        </span>
        {args && (
          <span className="font-mono text-2xs text-ink-muted">{args}</span>
        )}
        {tool.data !== undefined && (
          <button
            type="button"
            onClick={() => setShowRaw((v) => !v)}
            aria-expanded={showRaw}
            className="inline-flex items-center gap-0.5 rounded text-2xs font-medium text-accent hover:underline"
          >
            <ChevronIcon
              className={cn(
                "h-3 w-3 transition-transform duration-150",
                showRaw && "rotate-90"
              )}
            />
            {showRaw ? "Hide data" : "View data"}
          </button>
        )}
      </div>

      {showRaw && (
        <pre className="mt-2 max-h-64 overflow-auto rounded-md border border-line bg-surface-sunken p-3 font-mono text-2xs leading-relaxed text-ink-secondary">
          {JSON.stringify(tool.data, null, 2)}
        </pre>
      )}
    </div>
  );
}
