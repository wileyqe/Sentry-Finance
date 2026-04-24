interface SyntheticBadgeProps {
  compact?: boolean;
}

export default function SyntheticBadge({ compact = false }: SyntheticBadgeProps) {
  if (compact) {
    return (
      <span
        className="inline-flex items-center gap-0.5 text-[10px] font-medium
                   px-1.5 py-0.5 rounded-full
                   bg-accent/15 dark:bg-accent/25
                   text-[var(--accent-foreground)]"
        title="Synthetic data — generated for development"
      >
        <span aria-hidden="true" className="material-symbols-outlined text-[11px]">science</span>
        Demo
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 text-xs font-semibold
                 px-2.5 py-1 rounded-full
                 bg-accent/15 dark:bg-accent/25
                 text-[var(--accent-foreground)]"
      title="Synthetic data — generated for development"
    >
      <span aria-hidden="true" className="material-symbols-outlined text-[14px]">science</span>
      Synthetic
    </span>
  );
}
