import { forwardRef, type HTMLAttributes, type InputHTMLAttributes } from "react";
import { Search } from "lucide-react";
import { cn } from "@/lib/utils";

export interface FilterBarProps extends HTMLAttributes<HTMLDivElement> {}

const FilterBarRoot = forwardRef<HTMLDivElement, FilterBarProps>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      data-slot="filter-bar"
      className={cn("flex flex-wrap items-center gap-3 mb-4", className)}
      {...props}
    />
  )
);
FilterBarRoot.displayName = "FilterBar";

function Spacer() {
  return <div data-slot="filter-bar-spacer" className="flex-1" />;
}

export interface FilterBarSearchProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> {
  value: string;
  onChange: (value: string) => void;
}

function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
  className,
  ...props
}: FilterBarSearchProps) {
  return (
    <div data-slot="filter-bar-search" className={cn("relative", className)}>
      <Search
        aria-hidden="true"
        size={14}
        className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
      />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="pl-9 pr-3 py-1.5 text-sm bg-card border border-border rounded-md focus-ring placeholder:text-muted-foreground"
        {...props}
      />
    </div>
  );
}

type FilterBarComponent = typeof FilterBarRoot & {
  Spacer: typeof Spacer;
  Search: typeof SearchInput;
};

const FilterBar = FilterBarRoot as FilterBarComponent;
FilterBar.Spacer = Spacer;
FilterBar.Search = SearchInput;

export { FilterBar };
