import { Skeleton } from "@/components/ui/primitives";
import type { OverviewTile } from "@/lib/api";
import { formatValue } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The metric overview.
 *
 * Every number here comes from the same registry the agent queries, so the strip and the
 * chat can never disagree. The interface previously showed hardcoded figures in this
 * position; the rule now is that a tile either has real data or shows a skeleton.
 */

/** A minimal sparkline. No axes, no grid — it carries shape, not values. */
function Sparkline({ points, rising }: { points: number[]; rising: boolean }) {
  if (points.length < 2) return null;

  const width = 64;
  const height = 20;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;

  const path = points
    .map((value, i) => {
      const x = (i / (points.length - 1)) * width;
      const y = height - ((value - min) / span) * height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn("overflow-visible", rising ? "text-success" : "text-ink-muted")}
      aria-hidden="true"
    >
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * A delta chip.
 *
 * Direction is carried by an arrow glyph as well as colour, so the meaning survives for
 * a colour-blind reader and in a greyscale print. For churn, "up" is bad — the sign of
 * the number does not tell you whether it is good news, so the metric has to.
 */
function Delta({ value, metric }: { value: number; metric: string }) {
  const rising = value > 0;
  const higherIsWorse = metric === "churn_rate";
  const good = higherIsWorse ? !rising : rising;

  if (Math.abs(value) < 0.0005) {
    return <span className="text-2xs text-ink-muted">no change</span>;
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-2xs font-medium tabular-nums",
        good ? "text-success" : "text-danger"
      )}
    >
      <span aria-hidden="true">{rising ? "▲" : "▼"}</span>
      {Math.abs(value * 100).toFixed(1)}%
      <span className="sr-only">
        {rising ? "up" : "down"} versus the previous month
      </span>
    </span>
  );
}

function TileCard({ tile }: { tile: OverviewTile }) {
  const rising = (tile.delta ?? 0) > 0;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2.5">
      <div className="flex items-start justify-between gap-2">
        <span className="truncate text-2xs font-medium uppercase tracking-wide text-ink-muted">
          {tile.label}
        </span>
      </div>
      <div className="mt-1 flex items-end justify-between gap-2">
        <span className="text-md font-semibold tabular-nums text-ink">
          {formatValue(tile.value, tile.unit)}
        </span>
        <Sparkline points={tile.spark} rising={rising} />
      </div>
      {tile.delta !== null && (
        <div className="mt-1">
          <Delta value={tile.delta} metric={tile.metric} />
        </div>
      )}
    </div>
  );
}

export function MetricStrip({
  tiles,
  loading,
}: {
  tiles: OverviewTile[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-[74px]" />
        ))}
      </div>
    );
  }

  if (tiles.length === 0) return null;

  return (
    <div className="grid grid-cols-2 gap-2">
      {tiles.map((tile) => (
        <TileCard key={tile.metric} tile={tile} />
      ))}
    </div>
  );
}
