import {
  BellIcon,
  CompareIcon,
  GaugeIcon,
  PeopleIcon,
  TrendIcon,
} from "@/components/ui/icons";
import type { CurrentUser } from "@/lib/api";

/**
 * The first screen of a new conversation.
 *
 * Suggestions are filtered by role, so a viewer is never offered a question the system
 * will then refuse — an empty state that sets someone up to fail is worse than none.
 */

type Role = CurrentUser["role"];

const SUGGESTIONS: {
  text: string;
  hint: string;
  icon: (p: { className?: string }) => React.ReactElement;
  minRole: Role;
}[] = [
  {
    text: "What is my MRR for the last 6 months?",
    hint: "Monthly recurring revenue over time",
    icon: TrendIcon,
    minRole: "viewer",
  },
  {
    text: "What was my churn rate last quarter?",
    hint: "With the accounts behind the number",
    icon: GaugeIcon,
    minRole: "viewer",
  },
  {
    text: "How many active users did I have each month this year?",
    hint: "Distinct customers with activity",
    icon: PeopleIcon,
    minRole: "viewer",
  },
  {
    text: "Compare MRR between enterprise and smb",
    hint: "Segment against segment",
    icon: CompareIcon,
    minRole: "analyst",
  },
  {
    text: "Who are my top 5 customers by MRR?",
    hint: "Ranked by current revenue",
    icon: PeopleIcon,
    minRole: "analyst",
  },
  {
    text: "Show me active billing alerts",
    hint: "Usage spikes and overdue invoices",
    icon: BellIcon,
    minRole: "admin",
  },
];

const RANK: Record<Role, number> = { viewer: 0, analyst: 1, admin: 2 };

export function EmptyState({
  user,
  onPick,
}: {
  user: CurrentUser | null;
  onPick: (question: string) => void;
}) {
  const role = user?.role ?? "viewer";
  const available = SUGGESTIONS.filter((s) => RANK[role] >= RANK[s.minRole]);

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col justify-center px-4 py-10 sm:px-6">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">
          Ask about your metrics
        </h1>
        <p className="mt-2 max-w-xl text-md text-ink-secondary">
          Questions are answered from your own data using validated metric definitions —
          never from an estimate. Every figure shows the query behind it, so you can
          check the working.
        </p>
      </div>

      <div>
        <h2 className="mb-3 text-2xs font-semibold uppercase tracking-wide text-ink-muted">
          Try one of these
        </h2>
        <ul className="grid gap-2 sm:grid-cols-2">
          {available.map(({ text, hint, icon: Icon }) => (
            <li key={text}>
              <button
                type="button"
                onClick={() => onPick(text)}
                className="group flex w-full items-start gap-3 rounded-lg border border-line bg-surface p-3.5 text-left transition-colors hover:border-line-strong hover:bg-surface-hover"
              >
                <span className="mt-0.5 text-ink-muted transition-colors group-hover:text-accent">
                  <Icon className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-ink">{text}</span>
                  <span className="mt-0.5 block text-xs text-ink-muted">{hint}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {role !== "admin" && (
        <p className="mt-6 text-xs text-ink-muted">
          Signed in as <span className="font-medium text-ink-secondary">{role}</span>.
          Some metrics and tools are available only to higher roles.
        </p>
      )}
    </div>
  );
}
