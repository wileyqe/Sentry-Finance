---
name: web-design-guidelines
description: Audit UI code for accessibility, performance, and web best practices. Use when reviewing UI, checking accessibility, performing a design audit, or validating against best practices.
metadata:
  source: https://github.com/vudovn/antigravity-kit
  version: "1.0.0"
---

# Web Design Audit Guidelines

## Accessibility (WCAG 2.1 AA)
- **Color contrast**: 4.5:1 for normal text, 3:1 for large text (18px+ or 14px+ bold).
- **Focus visible**: Every interactive element must have a visible focus ring.
- **Touch targets**: Minimum 44×44px for mobile. 36×36px acceptable on desktop.
- **Alt text**: All images must have descriptive alt text. Decorative images: `alt=""`.
- **Keyboard navigation**: All interactions must work without a mouse.
- **ARIA roles**: Use semantic HTML first. Add ARIA only when semantic HTML is insufficient.

## Performance
- **LCP** (Largest Contentful Paint): < 2.5s. Prioritize above-fold content.
- **CLS** (Cumulative Layout Shift): < 0.1. Reserve space for images/async content.
- **FID/INP**: < 200ms. Avoid long-running JS on the main thread.
- **Image optimization**: Use WebP, lazy loading (`loading="lazy"`), explicit dimensions.
- **Font loading**: Use `font-display: swap`. Preload critical fonts.

## Semantics
- One `<h1>` per page. `<h2>`–`<h6>` in logical order.
- Use `<nav>`, `<main>`, `<aside>`, `<header>`, `<footer>` for landmarks.
- Buttons for actions, anchors for navigation. Never `<div onClick>`.
- Form inputs must have associated `<label>` elements.

## Responsive Design
- Test at 320px, 768px, 1024px, 1440px, 2560px.
- Tables must scroll horizontally on mobile (overflow-x-auto).
- Text must not overflow containers on small screens.
- Touch targets must pass 44px minimum on mobile.

## Design Consistency
- Consistent spacing system (8px grid).
- Consistent type scale (max 5 sizes per page).
- Consistent border radius (don't mix rounded-lg and rounded-full on the same type of element).
- Consistent color usage (don't use the same color for different semantic meanings).

## Audit Checklist
- [ ] All text passes WCAG AA contrast
- [ ] All interactive elements have focus rings
- [ ] Images have alt text
- [ ] Headings are in logical order
- [ ] Page works without JavaScript (graceful degradation)
- [ ] No horizontal scroll at 320px viewport
- [ ] Loading states for all async content
- [ ] Error states for all form inputs
