import { forwardRef, type HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const chipVariants = cva(
  "inline-flex items-center rounded-full text-xs font-medium px-2.5 py-0.5 transition-colors",
  {
    variants: {
      variant: {
        neutral: "chip-l2",
        gain: "text-gain bg-gain-subtle",
        loss: "text-loss bg-loss-subtle",
        accent: "bg-primary/10 text-primary",
        warning: "text-amber-700 bg-amber-500/10 dark:text-amber-300 dark:bg-amber-400/10",
      },
    },
    defaultVariants: { variant: "neutral" },
  }
);

export interface ChipProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof chipVariants> {}

const Chip = forwardRef<HTMLSpanElement, ChipProps>(
  ({ variant, className, ...props }, ref) => (
    <span
      ref={ref}
      data-slot="chip"
      className={cn(chipVariants({ variant }), className)}
      {...props}
    />
  )
);
Chip.displayName = "Chip";

export { Chip, chipVariants };
