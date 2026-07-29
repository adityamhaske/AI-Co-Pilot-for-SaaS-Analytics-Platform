import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatAxisValue, formatPeriodLabel, formatValue, humanisePeriod } from "@/lib/format";

/*
 * Chart rendering.
 *
 * Form follows the data's job:
 *   a metric over time      -> line (change over time)
 *   two segments compared   -> bar  (magnitude by identity)
 *   a single figure         -> stat tile, not a chart
 *   a ranking               -> table, because the labels are the point
 *
 * Series colours are slots 1 and 2 of a validated categorical palette; they are read
 * from CSS custom properties so both themes use steps chosen for their own surface.
 * A single series carries no legend — the caption already names it.
 */

type Row = Record<string, unknown>;
export type ChartData = Row | Row[];

interface SeriesPoint {
  date: string;
  value: number;
}
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

const isTrend = (d: ChartData): d is TrendResult =>
  !Array.isArray(d) && Array.isArray((d as TrendResult).series);
const isCompare = (d: ChartData): d is CompareResult =>
  !Array.isArray(d) && "segment_a" in d && "segment_b" in d;
const isSnapshot = (d: ChartData): d is SnapshotResult =>
  !Array.isArray(d) && typeof (d as SnapshotResult).value === "number";

const SERIES_1 = "rgb(var(--series-1))";
const SERIES_2 = "rgb(var(--series-2))";
const GRID = "rgb(var(--chart-grid))";
const AXIS_INK = "rgb(var(--ink-muted))";

const axisProps = {
  stroke: AXIS_INK,
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;

function ChartTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean;
  payload?: Array<{ value?: number | string; name?: string }>;
  label?: string | number;
  unit?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-line bg-surface-raised px-3 py-2 shadow-overlay">
      <div className="text-2xs uppercase tracking-wide text-ink-muted">
        {formatPeriodLabel(String(label ?? ""))}
      </div>
      {payload.map((entry, i) => (
        <div key={i} className="mt-0.5 text-sm font-medium tabular-nums text-ink">
          {formatValue(Number(entry.value), unit)}
        </div>
      ))}
    </div>
  );
}

function Figure({
  caption,
  children,
}: {
  caption: string;
  children: React.ReactNode;
}) {
  return (
    <figure className="mt-3 overflow-hidden rounded-lg border border-line bg-surface">
      <figcaption className="border-b border-line px-4 py-2.5 text-xs font-medium text-ink-secondary">
        {caption}
      </figcaption>
      <div className="p-3">{children}</div>
    </figure>
  );
}

function TrendChart({ data }: { data: TrendResult }) {
  const unit = data.unit;
  const points = data.series.map((p) => ({ ...p, label: formatPeriodLabel(p.date) }));
  const caption = data.label ?? data.metric ?? "Trend";

  // A flat line at zero reads as a rendering failure; say so instead.
  if (points.every((p) => p.value === 0)) {
    return (
      <Figure caption={caption}>
        <p className="px-1 py-6 text-center text-sm text-ink-muted">
          No activity in this period.
        </p>
      </Figure>
    );
  }

  return (
    <Figure caption={caption}>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="label" {...axisProps} minTickGap={24} />
            <YAxis
              {...axisProps}
              width={52}
              tickFormatter={(v: number) => formatAxisValue(v, unit)}
            />
            <Tooltip
              cursor={{ stroke: GRID, strokeWidth: 1 }}
              content={<ChartTooltip unit={unit} />}
            />
            <Line
              type="monotone"
              dataKey="value"
              name={caption}
              stroke={SERIES_1}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Figure>
  );
}

function CompareChart({ data }: { data: CompareResult }) {
  const unit = data.unit;
  const rows = [data.segment_a, data.segment_b];
  const caption = `${data.label ?? data.metric} by segment${
    data.period ? ` · ${humanisePeriod(data.period)}` : ""
  }`;

  return (
    <Figure caption={caption}>
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="name" {...axisProps} />
            <YAxis
              {...axisProps}
              width={52}
              tickFormatter={(v: number) => formatAxisValue(v, unit)}
            />
            <Tooltip
              cursor={{ fill: GRID, fillOpacity: 0.4 }}
              content={<ChartTooltip unit={unit} />}
            />
            {/* One hue per segment, matching the swatches below. Values are printed
                too, so identity never rests on colour alone. */}
            <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={72}>
              {rows.map((row, i) => (
                <Cell key={row.name} fill={i === 0 ? SERIES_1 : SERIES_2} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <dl className="mt-1 grid grid-cols-2 gap-2 px-1">
        {rows.map((row, i) => (
          <div key={row.name} className="flex items-baseline gap-2">
            <span
              aria-hidden="true"
              className="h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ backgroundColor: i === 0 ? SERIES_1 : SERIES_2 }}
            />
            <div className="min-w-0">
              <dt className="truncate text-xs text-ink-muted">{row.name}</dt>
              <dd className="text-sm font-semibold tabular-nums text-ink">
                {formatValue(row.value, unit)}
              </dd>
            </div>
          </div>
        ))}
      </dl>
    </Figure>
  );
}

function SnapshotTile({ data }: { data: SnapshotResult }) {
  const { numerator, denominator } = data;
  return (
    <figure className="mt-3 rounded-lg border border-line bg-surface px-4 py-3.5">
      <figcaption className="text-xs font-medium text-ink-secondary">
        {data.label ?? data.metric}
        {data.period && (
          <span className="text-ink-muted"> · {humanisePeriod(data.period)}</span>
        )}
      </figcaption>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">
        {formatValue(data.value, data.unit)}
      </div>
      {numerator && denominator && (
        // A bare ratio is not checkable; its terms are.
        <p className="mt-1.5 text-xs tabular-nums text-ink-muted">
          {formatValue(numerator.value)} {numerator.metric.replace(/_/g, " ")} of{" "}
          {formatValue(denominator.value)} {denominator.metric.replace(/_/g, " ")}
        </p>
      )}
    </figure>
  );
}

function RowTable({ rows }: { rows: Row[] }) {
  const columns = Object.keys(rows[0]).filter((c) => c !== "id");
  return (
    <Figure caption={`${rows.length} ${rows.length === 1 ? "row" : "rows"}`}>
      <div className="-m-1 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left">
              {columns.map((c) => (
                <th
                  key={c}
                  scope="col"
                  className="px-3 py-2 text-2xs font-semibold uppercase tracking-wide text-ink-muted"
                >
                  {c.replace(/_/g, " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0">
                {columns.map((c) => {
                  const value = row[c];
                  const numeric = typeof value === "number";
                  return (
                    <td
                      key={c}
                      className={`px-3 py-2 text-ink ${numeric ? "tabular-nums" : ""}`}
                    >
                      {numeric
                        ? formatValue(value, c === "mrr" ? "currency_usd" : undefined)
                        : String(value ?? "—")}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Figure>
  );
}

export function ResultChart({ data }: { data: ChartData }) {
  if (!data) return null;
  if (isTrend(data)) return data.series.length ? <TrendChart data={data} /> : null;
  if (isCompare(data)) return <CompareChart data={data} />;
  if (isSnapshot(data)) return <SnapshotTile data={data} />;
  if (Array.isArray(data) && data.length > 0 && typeof data[0] === "object") {
    return <RowTable rows={data} />;
  }
  return null;
}
