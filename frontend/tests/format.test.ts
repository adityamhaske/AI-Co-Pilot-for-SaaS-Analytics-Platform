/**
 * Value and label formatting.
 *
 * Formatting is driven by the metric's declared `unit`, which the backend sends with
 * every result — the UI never guesses whether a number is money. These pin that down,
 * because a currency rendered as a bare count is the kind of error nobody notices in
 * review but everybody notices in a screenshot.
 */
import { describe, expect, it } from "vitest";

import {
  formatAxisValue,
  formatPeriodLabel,
  humanisePeriod,
  initialsFor,
  relativeDateGroup,
} from "@/lib/format";
import { formatValue } from "@/lib/format";
import type { CurrentUser } from "@/lib/api";

describe("formatValue", () => {
  it("renders currency with a symbol and no stray cents at scale", () => {
    expect(formatValue(48250, "currency_usd")).toBe("$48,250");
    // Small amounts keep cents, because rounding $12.50 to $13 is wrong.
    expect(formatValue(12.5, "currency_usd")).toBe("$12.50");
  });

  it("renders a ratio as a percentage", () => {
    expect(formatValue(0.0508, "ratio")).toBe("5.1%");
    expect(formatValue(0, "ratio")).toBe("0.0%");
  });

  it("renders a count plainly with separators", () => {
    expect(formatValue(1240, "count")).toBe("1,240");
    expect(formatValue(9)).toBe("9");
  });

  it("shows an em dash rather than NaN", () => {
    expect(formatValue(Number.NaN, "currency_usd")).toBe("—");
    expect(formatValue(Number.POSITIVE_INFINITY)).toBe("—");
  });
});

describe("formatAxisValue", () => {
  it("abbreviates so axis labels do not collide", () => {
    expect(formatAxisValue(48250, "currency_usd")).toBe("$48K");
    expect(formatAxisValue(1_500_000, "currency_usd")).toBe("$1.5M");
    expect(formatAxisValue(750, "currency_usd")).toBe("$750");
  });

  it("keeps ratios as whole percentages on an axis", () => {
    expect(formatAxisValue(0.05, "ratio")).toBe("5%");
  });

  it("omits the currency symbol for counts", () => {
    expect(formatAxisValue(12000, "count")).toBe("12K");
  });
});

describe("formatPeriodLabel", () => {
  it("turns a month key into a readable month", () => {
    expect(formatPeriodLabel("2026-03")).toMatch(/Mar/);
    expect(formatPeriodLabel("2026-03")).toMatch(/2026/);
  });

  it("turns a day key into a day and month", () => {
    expect(formatPeriodLabel("2026-03-14")).toMatch(/Mar/);
    expect(formatPeriodLabel("2026-03-14")).toMatch(/14/);
  });

  it("passes anything else through untouched", () => {
    // The backend used to emit a "no_data" sentinel; a formatter must not invent a date.
    expect(formatPeriodLabel("no_data")).toBe("no_data");
    expect(formatPeriodLabel("")).toBe("");
  });
});

describe("humanisePeriod", () => {
  it("makes a period key readable", () => {
    expect(humanisePeriod("last_quarter")).toBe("last quarter");
    expect(humanisePeriod(undefined)).toBe("");
  });
});

describe("relativeDateGroup", () => {
  const iso = (daysAgo: number) => {
    const d = new Date();
    d.setHours(12, 0, 0, 0);
    d.setDate(d.getDate() - daysAgo);
    return d.toISOString();
  };

  it("groups by how a person thinks about recency", () => {
    expect(relativeDateGroup(iso(0))).toBe("Today");
    expect(relativeDateGroup(iso(1))).toBe("Yesterday");
    expect(relativeDateGroup(iso(3))).toBe("Previous 7 days");
    expect(relativeDateGroup(iso(14))).toBe("Previous 30 days");
    expect(relativeDateGroup(iso(90))).toBe("Earlier");
  });

  it("does not crash on a missing or invalid timestamp", () => {
    expect(relativeDateGroup(null)).toBe("Earlier");
    expect(relativeDateGroup("not a date")).toBe("Earlier");
  });
});

describe("initialsFor", () => {
  const user = (email: string) => ({ email, role: "admin" }) as CurrentUser;

  it("derives initials from the signed-in user, never a hardcoded value", () => {
    expect(initialsFor(user("ada.lovelace@example.com"))).toBe("AL");
    expect(initialsFor(user("first_last@example.com"))).toBe("FL");
    expect(initialsFor(user("admin@test.com"))).toBe("AD");
  });

  it("falls back rather than rendering undefined", () => {
    expect(initialsFor(null)).toBe("?");
  });
});
