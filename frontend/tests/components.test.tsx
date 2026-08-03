/**
 * Component behaviour.
 *
 * Focused on the things a visual check does not catch: which chart form a payload
 * selects, whether provenance is actually reachable, and whether the composer's keyboard
 * contract holds. Recharts renders to SVG that jsdom cannot measure, so the chart tests
 * assert the *choice* of form and its caption rather than pixel output.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "@/features/chat/Composer";
import { EmptyState } from "@/features/chat/EmptyState";
import { MessageList } from "@/features/chat/MessageList";
import { ResultChart } from "@/features/chart/ResultChart";
import { ToolTrace } from "@/features/chat/ToolTrace";
import type { CurrentUser } from "@/lib/api";

// ResponsiveContainer needs a measurable box, which jsdom does not provide.
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 600, height: 300 }}>{children}</div>
    ),
  };
});

const asUser = (role: CurrentUser["role"]): CurrentUser => ({
  id: "u1",
  email: "someone@example.com",
  role,
  tenant_id: "t1",
});

// ---------------------------------------------------------------------------
// Chart form selection
// ---------------------------------------------------------------------------

describe("ResultChart form selection", () => {
  it("captions a trend with the metric label", () => {
    render(
      <ResultChart
        data={{
          metric: "mrr",
          label: "Monthly Recurring Revenue",
          unit: "currency_usd",
          series: [
            { date: "2026-01", value: 100 },
            { date: "2026-02", value: 200 },
          ],
        }}
      />
    );
    expect(screen.getByText("Monthly Recurring Revenue")).toBeInTheDocument();
  });

  it("says so plainly when a trend is entirely zero", () => {
    // A flat line on the baseline reads as a broken chart, not as an absence of activity.
    render(
      <ResultChart
        data={{
          metric: "mrr",
          label: "Monthly Recurring Revenue",
          unit: "currency_usd",
          series: [
            { date: "2026-01", value: 0 },
            { date: "2026-02", value: 0 },
          ],
        }}
      />
    );
    expect(screen.getByText(/no activity in this period/i)).toBeInTheDocument();
  });

  it("labels both segments and prints their values, not colour alone", () => {
    render(
      <ResultChart
        data={{
          metric: "mrr",
          label: "Monthly Recurring Revenue",
          unit: "currency_usd",
          period: "last_month",
          segment_a: { name: "enterprise", value: 5400 },
          segment_b: { name: "smb", value: 2511 },
        }}
      />
    );
    expect(screen.getByText("enterprise")).toBeInTheDocument();
    expect(screen.getByText("smb")).toBeInTheDocument();
    // Identity never rests on hue: the numbers are on screen too.
    expect(screen.getByText("$5,400")).toBeInTheDocument();
    expect(screen.getByText("$2,511")).toBeInTheDocument();
  });

  it("renders a single figure as a stat tile, and shows a ratio's terms", () => {
    render(
      <ResultChart
        data={{
          metric: "churn_rate",
          label: "Churn Rate",
          unit: "ratio",
          period: "last_quarter",
          value: 0.1667,
          numerator: { metric: "churned_subscriptions", value: 2 },
          denominator: { metric: "active_subscriptions_at_start", value: 12 },
        }}
      />
    );
    expect(screen.getByText("16.7%")).toBeInTheDocument();
    // "16.7%" alone is not checkable; "2 of 12" is.
    expect(screen.getByText(/2 churned subscriptions of 12/i)).toBeInTheDocument();
  });

  it("renders a ranking as a table with its columns", () => {
    render(
      <ResultChart
        data={[
          { id: "c1", name: "Nichols-Baker", mrr: 4200, segment: "midmarket" },
          { id: "c2", name: "Hoover Ltd", mrr: 3100, segment: "midmarket" },
        ]}
      />
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("Nichols-Baker")).toBeInTheDocument();
    // `id` is noise in a table meant for a person.
    expect(screen.queryByText("id")).not.toBeInTheDocument();
  });

  it("renders nothing for an unrecognised payload rather than crashing", () => {
    const { container } = render(<ResultChart data={{ something: "unexpected" }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

// ---------------------------------------------------------------------------
// Provenance
// ---------------------------------------------------------------------------

describe("ToolTrace", () => {
  const tool = {
    name: "get_metric_trend",
    input: { metric: "mrr", granularity: "month" },
    data: { series: [{ date: "2026-01", value: 100 }] },
  };

  it("names the tool and the arguments it was called with", () => {
    render(<ToolTrace tool={tool} />);
    expect(screen.getByText("get_metric_trend")).toBeInTheDocument();
    expect(screen.getByText(/metric: mrr/)).toBeInTheDocument();
    expect(screen.getByText(/granularity: month/)).toBeInTheDocument();
  });

  it("keeps the raw rows one click away", async () => {
    render(<ToolTrace tool={tool} />);
    expect(screen.queryByText(/"series"/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /view data/i }));
    await waitFor(() =>
      expect(screen.getByText(/"series"/)).toBeInTheDocument()
    );
  });

  it("omits empty arguments instead of printing blanks", () => {
    render(<ToolTrace tool={{ name: "list_active_alerts", input: {}, data: [] }} />);
    expect(screen.getByText("list_active_alerts")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Composer
// ---------------------------------------------------------------------------

describe("Composer", () => {
  it("submits on Enter", async () => {
    const onSubmit = vi.fn();
    render(<Composer onSubmit={onSubmit} onCancel={vi.fn()} busy={false} />);

    const box = screen.getByLabelText(/ask a question/i);
    await userEvent.type(box, "What is my MRR?{Enter}");

    expect(onSubmit).toHaveBeenCalledWith("What is my MRR?");
  });

  it("inserts a newline on Shift+Enter instead of sending", async () => {
    const onSubmit = vi.fn();
    render(<Composer onSubmit={onSubmit} onCancel={vi.fn()} busy={false} />);

    const box = screen.getByLabelText(/ask a question/i);
    await userEvent.type(box, "line one{Shift>}{Enter}{/Shift}line two");

    expect(onSubmit).not.toHaveBeenCalled();
    expect((box as HTMLTextAreaElement).value).toContain("\n");
  });

  it("refuses to send whitespace", async () => {
    const onSubmit = vi.fn();
    render(<Composer onSubmit={onSubmit} onCancel={vi.fn()} busy={false} />);

    await userEvent.type(screen.getByLabelText(/ask a question/i), "   {Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("clears the box after sending", async () => {
    render(<Composer onSubmit={vi.fn()} onCancel={vi.fn()} busy={false} />);
    const box = screen.getByLabelText(/ask a question/i);
    await userEvent.type(box, "a question{Enter}");
    expect((box as HTMLTextAreaElement).value).toBe("");
  });

  it("offers a stop control while streaming, and no send", () => {
    render(<Composer onSubmit={vi.fn()} onCancel={vi.fn()} busy />);
    expect(screen.getByRole("button", { name: /stop generating/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /send question/i })).not.toBeInTheDocument();
  });

  it("cancels when the stop control is used", async () => {
    const onCancel = vi.fn();
    render(<Composer onSubmit={vi.fn()} onCancel={onCancel} busy />);
    await userEvent.click(screen.getByRole("button", { name: /stop generating/i }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("does not submit while busy", async () => {
    const onSubmit = vi.fn();
    render(<Composer onSubmit={onSubmit} onCancel={vi.fn()} busy />);
    await userEvent.type(screen.getByLabelText(/ask a question/i), "queued{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

describe("EmptyState", () => {
  it("only offers a viewer questions a viewer can actually ask", () => {
    // Suggesting a question the system will then refuse sets the user up to fail.
    render(<EmptyState user={asUser("viewer")} onPick={vi.fn()} />);
    expect(screen.getByText(/what is my mrr/i)).toBeInTheDocument();
    expect(screen.queryByText(/top 5 customers/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/billing alerts/i)).not.toBeInTheDocument();
  });

  it("offers an analyst segment and ranking questions", () => {
    render(<EmptyState user={asUser("analyst")} onPick={vi.fn()} />);
    expect(screen.getByText(/compare mrr/i)).toBeInTheDocument();
    expect(screen.getByText(/top 5 customers/i)).toBeInTheDocument();
    expect(screen.queryByText(/billing alerts/i)).not.toBeInTheDocument();
  });

  it("offers an admin everything", () => {
    render(<EmptyState user={asUser("admin")} onPick={vi.fn()} />);
    expect(screen.getByText(/billing alerts/i)).toBeInTheDocument();
  });

  it("sends the suggestion text when one is picked", async () => {
    const onPick = vi.fn();
    render(<EmptyState user={asUser("viewer")} onPick={onPick} />);
    await userEvent.click(screen.getByText(/what is my mrr/i));
    expect(onPick).toHaveBeenCalledWith("What is my MRR for the last 6 months?");
  });

  it("falls back to viewer suggestions when the user has not loaded", () => {
    render(<EmptyState user={null} onPick={vi.fn()} />);
    expect(screen.getByText(/what is my mrr/i)).toBeInTheDocument();
    expect(screen.queryByText(/billing alerts/i)).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Error notices
//
// The backend distinguishes a vendor outage from a step limit; the UI used to render
// both as the same red box. "The answer above is incomplete, ask something narrower" and
// "nothing worked" are different instructions and should not look identical.
// ---------------------------------------------------------------------------

describe("error notices", () => {
  const base = {
    id: "m1",
    role: "assistant" as const,
    content: "Your MRR is $5,600.",
    tools: [],
  };

  it("treats a step limit as a warning, not a failure", () => {
    render(
      <MessageList
        messages={[
          { ...base, error: "Stopped after 6 steps.", errorKind: "step_limit" as const },
        ]}
        user={null}
        activeTool={null}
      />,
    );
    const notice = screen.getByRole("status");
    expect(notice).toHaveAttribute("data-error-kind", "step_limit");
    expect(notice.className).toContain("warning");
    expect(notice.className).not.toContain("danger");
    // The partial answer is still shown — the warning is about it, not instead of it.
    expect(screen.getByText(/Your MRR is \$5,600/)).toBeInTheDocument();
    expect(screen.getByText(/narrower question/i)).toBeInTheDocument();
  });

  it("treats a provider outage as a failure", () => {
    render(
      <MessageList
        messages={[
          { ...base, content: "", error: "Provider unreachable.", errorKind: "provider" as const },
        ]}
        user={null}
        activeTool={null}
      />,
    );
    const notice = screen.getByRole("alert");
    expect(notice).toHaveAttribute("data-error-kind", "provider");
    expect(notice.className).toContain("danger");
    expect(screen.getByText(/Model provider unavailable/i)).toBeInTheDocument();
  });

  it("falls back to a failure when the backend sends no kind", () => {
    render(
      <MessageList
        messages={[{ ...base, content: "", error: "Boom." }]}
        user={null}
        activeTool={null}
      />,
    );
    const notice = screen.getByRole("alert");
    expect(notice).toHaveAttribute("data-error-kind", "internal");
    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument();
  });

  it("does not interrupt a screen reader for a partial answer", () => {
    // role=status is polite; role=alert is assertive. A warning that arrives while the
    // user is reading the answer above it must not cut that off.
    render(
      <MessageList
        messages={[{ ...base, error: "Stopped early.", errorKind: "timeout" as const }]}
        user={null}
        activeTool={null}
      />,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
