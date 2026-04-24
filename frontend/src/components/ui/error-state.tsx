import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import { AlertCircle, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export interface ErrorStateProps extends HTMLAttributes<HTMLDivElement> {
  title?: string;
  description?: ReactNode;
  onRetry?: () => void;
  retryLabel?: string;
}

const ErrorState = forwardRef<HTMLDivElement, ErrorStateProps>(
  (
    {
      title = "Something went wrong",
      description,
      onRetry,
      retryLabel = "Try again",
      className,
      ...props
    },
    ref
  ) => (
    <div
      ref={ref}
      role="alert"
      data-slot="error-state"
      className={cn(
        "card-l1 p-8 flex flex-col items-center text-center gap-3",
        className
      )}
      {...props}
    >
      <AlertCircle className="text-loss size-8" aria-hidden="true" />
      <h3 className="text-base font-semibold text-foreground">{title}</h3>
      {description && (
        <p className="text-sm text-muted-foreground max-w-md">{description}</p>
      )}
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-2">
          <RotateCcw aria-hidden="true" />
          {retryLabel}
        </Button>
      )}
    </div>
  )
);
ErrorState.displayName = "ErrorState";

export { ErrorState };
