---
name: tailwind-patterns
description: Tailwind CSS best practices for dark mode, responsive design, component extraction, and the modern color system. Use when writing Tailwind classes or reviewing component styling.
---

# Tailwind CSS Patterns

## Core Principles
- **Mobile-first**: Write base styles for mobile, add `sm:`, `md:`, `lg:` for larger screens.
- **8px grid**: Use Tailwind's spacing scale (1 unit = 4px). Prefer `p-4` (16px), `p-6` (24px), `p-8` (32px).
- **Semantic over atomic**: Extract repeated patterns into CSS classes, not components.
- **Dark mode**: Use `dark:` prefix. Set `darkMode: 'class'` in config.

## Dark Mode Pattern
```tsx
// Good — explicit dark variants
<div className="bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100">

// Good — use CSS variables for brand colors
<div className="bg-[var(--color-primary)] text-white">
```

## Layout Patterns
```tsx
// Sidebar layout
<div className="flex h-screen overflow-hidden">
  <aside className="w-64 flex-shrink-0">...</aside>
  <main className="flex-1 overflow-y-auto">...</main>
</div>

// Card grid
<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
```

## Color: OKLCH (Perceptual Uniformity)
- Use `oklch(L C H)` for design tokens — perceptually uniform, great for dark mode.
- Avoid pure black/white: use `oklch(0.10 0 0)` for dark bg, `oklch(0.97 0 0)` for light bg.
- Interactive state: add `/80` (opacity) or adjust L by ±0.05 for hover.

## Animation Best Practices
```tsx
// Prefer CSS transitions over JS animations when possible
className="transition-all duration-200 ease-out"

// For entrance animations — only animate transform + opacity
className="transition-[opacity,transform] duration-300 ease-out"

// Hover: scale + shadow together feels premium
className="hover:scale-[1.01] hover:shadow-lg transition-all duration-200"
```

## Anti-Patterns
- ❌ `!important` via `!` prefix — indicates conflicting styles
- ❌ Arbitrary values for things that should be tokens: `w-[247px]` → align to grid
- ❌ Mixing Tailwind spacing with inline pixel styles
- ❌ `transition-all` on heavy properties (layout/paint) — be specific
- ❌ Hardcoding dark colors without `dark:` variants
- ❌ Non-8px values without good reason (e.g. `p-5` = 20px is fine, `p-[13px]` is not)
