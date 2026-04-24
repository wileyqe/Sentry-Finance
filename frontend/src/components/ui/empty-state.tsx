import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface EmptyStateProps extends HTMLAttributes<HTMLDivElement> {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}

const EmptyState = forwardRef<HTMLDivElement, EmptyStateProps>(
  ({ icon, title, description, action, className, ...props }, ref) => (
    <div
      ref={ref}
      data-slot="empty-state"
      className={cn(
        "flex flex-col items-center justify-center text-center py-12 px-6",
        className
      )}
      {...props}
    >
      {icon && (
        <div data-slot="empty-state-icon" className="mb-4 text-muted-foreground [&_svg]:size-10">
          {icon}
        </div>
      )}
      <h3
        data-slot="empty-state-title"
        className="text-base font-semibold text-foreground mb-1.5"
      >
        {title}
      </h3>
      {description && (
        <p
          data-slot="empty-state-description"
          className="text-sm text-muted-foreground max-w-md"
        >
          {description}
        </p>
      )}
      {action && (
        <div data-slot="empty-state-action" className="mt-5">
          {action}
        </div>
      )}
    </div>
  )
);
EmptyState.displayName = "EmptyState";

export { EmptyState };
