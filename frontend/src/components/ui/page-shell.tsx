import { motion, type HTMLMotionProps } from "framer-motion";
import { forwardRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

const springTransition = { type: "spring", stiffness: 300, damping: 30 } as const;

export const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.05 },
  },
};

export const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  visible: { opacity: 1, y: 0, transition: springTransition },
};

export interface PageShellProps extends HTMLMotionProps<"div"> {
  children: ReactNode;
}

const PageShellRoot = forwardRef<HTMLDivElement, PageShellProps>(
  ({ children, className, ...props }, ref) => (
    <motion.div
      ref={ref}
      data-slot="page-shell"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className={cn(
        "flex-1 flex flex-col min-w-0 bg-background overflow-auto custom-scrollbar",
        className
      )}
      {...props}
    >
      {children}
    </motion.div>
  )
);
PageShellRoot.displayName = "PageShell";

export interface PageShellSectionProps extends HTMLMotionProps<"section"> {
  children: ReactNode;
}

function Section({ children, className, ...props }: PageShellSectionProps) {
  return (
    <motion.section
      data-slot="page-shell-section"
      variants={itemVariants}
      className={cn(className)}
      {...props}
    >
      {children}
    </motion.section>
  );
}

type PageShellComponent = typeof PageShellRoot & {
  Section: typeof Section;
};

const PageShell = PageShellRoot as PageShellComponent;
PageShell.Section = Section;

export { PageShell };
