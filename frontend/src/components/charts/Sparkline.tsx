/**
 * Sparkline — tiny inline-SVG line chart.
 *
 * Axis-free, grid-free, tooltip-free. Sized for 32–40px tall; fixed
 * viewBox so the line scales crisply inside `width`/`height`. Values
 * are normalized to `[pad, height-pad]`; a perfectly flat series still
 * renders a mid-height line. Modeled on the cumulative-spend sparkline
 * on `DashboardPage.tsx:877`.
 */

interface SparklineProps {
  values: number[];
  width?: number;
  height?: number;
  strokeClassName?: string;
  ariaLabel: string;
}

export function Sparkline({
  values,
  width = 120,
  height = 32,
  strokeClassName = "stroke-foreground",
  ariaLabel,
}: SparklineProps) {
  const clean = values.filter((v) => Number.isFinite(v));
  if (clean.length < 2) return null;

  const pad = 2;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;

  const points = clean.map((v, i) => {
    const x = (i / (clean.length - 1)) * (width - pad * 2) + pad;
    const y = height - pad - ((v - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });

  const d = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
  const [lastX, lastY] = points[points.length - 1];

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={`h-[${height}px] w-[${width}px]`}
      style={{ width, height }}
      role="img"
      aria-label={ariaLabel}
    >
      <path
        d={d}
        fill="none"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={strokeClassName}
      />
      <circle cx={lastX} cy={lastY} r={2} className={strokeClassName.replace("stroke-", "fill-")} />
    </svg>
  );
}
