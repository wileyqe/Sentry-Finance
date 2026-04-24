import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface PageHeaderProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}

const PageHeader = forwardRef<HTMLDivElement, PageHeaderProps>(
  ({ title, subtitle, actions, className, ...props }, ref) => (
    <div
      ref={ref}
      data-slot="page-header"
      className={cn("flex items-start justify-between gap-4 mb-6", className)}
      {...props}
    >
      <div className="min-w-0">
        <h1
          data-slot="page-header-title"
          className="text-2xl font-bold tracking-tight text-foreground"
        >
          {title}
        </h1>
        {subtitle && (
          <p
            data-slot="page-header-subtitle"
            className="text-sm text-muted-foreground mt-0.5"
          >
            {subtitle}
          </p>
        )}
      </div>
      {actions && (
        <div
          data-slot="page-header-actions"
          className="flex items-center gap-2 shrink-0"
        >
          {actions}
        </div>
      )}
    </div>
  )
);
PageHeader.displayName = "PageHeader";

export { PageHeader };
