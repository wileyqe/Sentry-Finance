import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Card } from "./card";

export interface StatCardProps extends HTMLAttributes<HTMLDivElement> {
  label: ReactNode;
  value: ReactNode;
  /** Percent delta. Positive → gain, negative → loss, zero → neutral. */
  delta?: number;
  /** Small label next to the delta, e.g. "this month". */
  deltaLabel?: ReactNode;
  /** Optional trend slot (e.g. <Sparkline>). */
  trend?: ReactNode;
}

const StatCard = forwardRef<HTMLDivElement, StatCardProps>(
  ({ label, value, delta, deltaLabel, trend, className, ...props }, ref) => {
    const deltaColor =
      delta === undefined
        ? ""
        : delta > 0
          ? "text-gain"
          : delta < 0
            ? "text-loss"
            : "text-neutral";
    const deltaSign = delta === undefined ? "" : delta > 0 ? "+" : "";

    return (
      <Card
        ref={ref}
        data-slot="stat-card"
        className={cn("p-5 flex flex-col gap-3", className)}
        {...props}
      >
        <div className="text-label">{label}</div>
        <div className="stat-value">{value}</div>
        {(delta !== undefined || trend) && (
          <div className="flex items-center justify-between gap-3 mt-auto">
            {delta !== undefined && (
              <span
                data-slot="stat-card-delta"
                className={cn("text-xs font-semibold inline-flex items-baseline gap-1", deltaColor)}
              >
                <span className="text-numeric">
                  {deltaSign}
                  {delta.toFixed(1)}%
                </span>
                {deltaLabel && (
                  <span className="font-normal text-muted-foreground">
                    {deltaLabel}
                  </span>
                )}
              </span>
            )}
            {trend && (
              <div data-slot="stat-card-trend" className="shrink-0">
                {trend}
              </div>
            )}
          </div>
        )}
      </Card>
    );
  }
);
StatCard.displayName = "StatCard";

export { StatCard };
