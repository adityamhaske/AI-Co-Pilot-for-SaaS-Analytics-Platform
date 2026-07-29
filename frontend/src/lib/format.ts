import type { CurrentUser } from "@/lib/api";

/**
 * Formatting driven by the metric's declared unit, which the backend sends with every
 * result. The UI never guesses whether a number is money.
 */
export function formatValue(value: number, unit?: string): string {
  if (!Number.isFinite(value)) return "—";
  if (unit === "currency_usd") {
    return value.toLocaleString(undefined, {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: value >= 1000 ? 0 : 2,
    });
  }
  if (unit === "ratio") return `${(value * 100).toFixed(1)}%`;
  return value.toLocaleString();
}

/** Compact axis labels: 12000 -> "12K". Full precision stays in the tooltip. */
export function formatAxisValue(value: number, unit?: string): string {
  if (!Number.isFinite(value)) return "";
  if (unit === "ratio") return `${Math.round(value * 100)}%`;

  const prefix = unit === "currency_usd" ? "$" : "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${prefix}${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${prefix}${Math.round(value / 1_000)}K`;
  return `${prefix}${value.toLocaleString()}`;
}

/** "2026-03" -> "Mar 2026"; "2026-03-14" -> "14 Mar". Falls back to the raw label. */
export function formatPeriodLabel(label: string): string {
  const month = /^(\d{4})-(\d{2})$/.exec(label);
  if (month) {
    const date = new Date(Number(month[1]), Number(month[2]) - 1, 1);
    return date.toLocaleDateString(undefined, { month: "short", year: "numeric" });
  }
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(label);
  if (day) {
    const date = new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3]));
    return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }
  return label;
}

export function humanisePeriod(period?: string): string {
  if (!period) return "";
  return period.replace(/_/g, " ");
}

/** Group conversations the way a person thinks about them, not by raw timestamp. */
export function relativeDateGroup(iso: string | null): string {
  if (!iso) return "Earlier";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "Earlier";

  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const days = Math.floor((startOfToday.getTime() - then.getTime()) / 86_400_000);

  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "Previous 7 days";
  if (days < 30) return "Previous 30 days";
  return "Earlier";
}

export function formatTimestamp(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Avatar initials from the signed-in user. Never hardcoded. */
export function initialsFor(user: CurrentUser | null): string {
  if (!user?.email) return "?";
  const [local] = user.email.split("@");
  const parts = local.split(/[._-]/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return local.slice(0, 2).toUpperCase();
}

export function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
