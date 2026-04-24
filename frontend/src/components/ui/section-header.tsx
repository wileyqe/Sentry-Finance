import { useState, type HTMLAttributes, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export interface SectionHeaderProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title: ReactNode;
  actions?: ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
  children?: ReactNode;
}

export function SectionHeader({
  title,
  actions,
  collapsible = false,
  defaultOpen = true,
  children,
  className,
  ...props
}: SectionHeaderProps) {
  const [open, setOpen] = useState(defaultOpen);
  const showChildren = !collapsible || open;

  const header = (
    <div
      data-slot="section-header"
      className={cn(
        "flex items-center justify-between gap-3 px-5 py-3 rounded-t-xl transition-colors duration-150",
        collapsible &&
          "cursor-pointer select-none hover:bg-muted/60 dark:hover:bg-muted/30",
        className
      )}
      onClick={collapsible ? () => setOpen((o) => !o) : undefined}
      role={collapsible ? "button" : undefined}
      tabIndex={collapsible ? 0 : undefined}
      aria-expanded={collapsible ? open : undefined}
      onKeyDown={
        collapsible
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setOpen((o) => !o);
              }
            }
          : undefined
      }
      {...props}
    >
      <div className="flex items-center gap-2 min-w-0">
        {collapsible && (
          <span className="text-muted-foreground shrink-0">
            {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </span>
        )}
        <h2 className="text-sm font-semibold tracking-tight text-foreground truncate">
          {title}
        </h2>
      </div>
      {actions && (
        <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
          {actions}
        </div>
      )}
    </div>
  );

  if (children === undefined) return header;
  return (
    <>
      {header}
      {showChildren && children}
    </>
  );
}
