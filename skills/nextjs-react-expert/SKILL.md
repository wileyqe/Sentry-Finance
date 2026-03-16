---
name: nextjs-react-expert
description: React & Vite performance expert covering re-render optimization, bundle size, async patterns, and advanced patterns. Use when reviewing component performance, optimizing data fetching, or debugging slow renders.
metadata:
  source: https://github.com/vudovn/antigravity-kit
  version: "1.0.0"
---

# React Performance Expert

## Quick Decision Tree
1. **Slow initial load?** → Bundle size (lazy imports, code splitting)
2. **Slow data fetch?** → Async patterns (parallel fetches, no serial waterfalls)
3. **Unnecessary re-renders?** → useMemo, useCallback, memo()
4. **Slow animations?** → GPU-safe properties only (transform, opacity)
5. **Large lists?** → Virtualization (react-window / tanstack-virtual)

## Critical Patterns

### Parallel Data Fetching (Eliminate Waterfalls)
```tsx
// ❌ Serial — each waits for the previous
const a = await fetchA();
const b = await fetchB(a.id);

// ✅ Parallel — fire all at once
const [a, b, c] = await Promise.all([fetchA(), fetchB(), fetchC()]);
```

### Memoization Rules
```tsx
// useMemo — expensive computations only
const sorted = useMemo(() => data.sort(...), [data]);

// useCallback — stable function refs for child props
const handler = useCallback((id) => setSelected(id), []);

// memo() — pure components receiving stable props
const Row = memo(({ item }) => <div>{item.name}</div>);
```

### State Colocation
- State only as high as needed.
- Extract local UI state (open/closed, hover) into the component that owns it.
- Never put ephemeral UI state in global store.

### Re-render Checklist
- [ ] Are object/array props memoized?
- [ ] Does useEffect have correct dependency array?
- [ ] Are handlers wrapped in useCallback?
- [ ] Are expensive derivations in useMemo?
- [ ] Are lists using stable `key` props?

## Anti-Patterns
- ❌ Creating new objects/arrays inline in JSX (new ref on every render)
- ❌ Anonymous functions as event handlers in render (breaks memo)
- ❌ useEffect with missing or empty deps that runs on every render
- ❌ Fetching in useEffect without abort controllers (memory leaks)
- ❌ State that could be derived from existing state (derive, don't store)

## Bundle Size
- Use dynamic imports for heavy components: `const Chart = lazy(() => import('./Chart'))`
- Tree-shake imports: `import { specific } from 'lib'` not `import * as lib`
- Analyze with: `npx vite-bundle-visualizer`
