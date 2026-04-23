/**
 * Skeleton loading placeholders.
 * Provides pulse-animated rectangles that match the page layout.
 */

import { cn } from "@/lib/utils";

interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-slate-200 dark:bg-slate-800",
        className
      )}
    />
  );
}

/** Three KPI cards skeleton matching DashboardPage top row */
export function KpiCardsSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
      {[0, 1, 2].map((i) => (
        <div key={i}>
          <Skeleton className="h-4 w-24 mb-4" />
          <Skeleton className="h-12 w-48 mb-6" />
          <Skeleton className="h-0.5 w-full" />
        </div>
      ))}
    </div>
  );
}

/** Chart area skeleton */
export function ChartSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("flex flex-col", className)}>
      <div className="flex items-end justify-between mb-4 pb-4 border-b border-slate-200 dark:border-slate-800 h-[84px]">
        <div>
          <Skeleton className="h-8 w-36 mb-2" />
          <Skeleton className="h-3 w-20" />
        </div>
        <Skeleton className="h-8 w-28 rounded-md" />
      </div>
      <Skeleton className="flex-1 w-full min-h-[200px] rounded-md" />
    </div>
  );
}

/** Transaction list skeleton */
export function TransactionListSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="space-y-0">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="py-4 border-b border-slate-100 dark:border-slate-800/50 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Skeleton className="h-8 w-8 rounded-full" />
            <div>
              <Skeleton className="h-4 w-32 mb-1" />
              <Skeleton className="h-3 w-24" />
            </div>
          </div>
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

