---
name: frontend-design
description: Comprehensive frontend design system covering UX psychology, color theory, typography, layout, visual effects, and animation. Use when building UI components, designing pages, or reviewing aesthetics.
---

# Frontend Design System

## 1. Constraint Analysis (ALWAYS FIRST)
- Who is the user? (developer, consumer, enterprise, creative)
- What device? (mobile, desktop, tablet)
- What emotion should they feel? (trust, excitement, calm, power)
- What action must they take? (convert, explore, analyze)

## 2. UX Psychology Principles
- **Hick's Law**: Fewer choices = faster decisions. Limit nav items to 7±2.
- **Fitts's Law**: Bigger targets = easier to hit. CTAs should be ≥44px touch target.
- **Jakob's Law**: Users spend most time on other sites. Match familiar patterns.
- **Von Restorff Effect**: Isolated items are remembered. Use sparingly for CTAs.
- **Miller's Law**: 7±2 chunks in working memory. Group related items.

## 3. Layout Principles
- **8-Point Grid**: All spacing in multiples of 8 (4 for micro-adjustments).
- **Golden Ratio**: φ=1.618. Use for proportions — sidebar:content, card ratios.
- **Visual Weight**: Heavier elements anchor the layout. Place emphasis intentionally.
- **White Space**: Breathing room IS design. Don't fear emptiness.

## 4. Color Principles (60-30-10 Rule)
- **60%** — dominant neutral (background, large surfaces)
- **30%** — secondary (cards, sidebars, panels)
- **10%** — accent (CTAs, highlights, brand moments)
- Use OKLCH for perceptually uniform colors. Avoid HSL for precision work.

## 5. Typography Principles
- **Scale**: Use a modular scale (1.250 Major Third or 1.333 Perfect Fourth).
- **Hierarchy**: Max 3 weights on one page. Contrast weight, not just size.
- **Line height**: Body 1.5–1.7, Headlines 1.1–1.3, UI labels 1.0–1.2.
- **Tabular nums**: Always use `font-variant-numeric: tabular-nums` for data.
- **Letter spacing**: Only on uppercase labels (0.05–0.1em). Never on body text.

## 6. Visual Effects Principles
- **Glassmorphism**: backdrop-blur + semi-transparent bg + subtle border. Use on floating panels over rich backgrounds.
- **Shadow Hierarchy**: 3 levels — ambient (0 1px 3px), raised (0 4px 16px), floating (0 16px 48px).
- **Gradients**: Linear for backgrounds, radial for glow/spotlight effects. Max 2 stops for clean gradients.
- **Border tokens**: 1px borders for cards, 2px for focus rings, 0 for floating elements.

## 7. Animation Principles
- **Micro**: 100–200ms. Hover states, button presses.
- **Transitions**: 200–300ms. Panel opens, tab switches.
- **Entrances**: 300–500ms. Page loads, modal opens.
- **Dramatic**: 500–800ms. Hero animations only.
- **Easing**: ease-out for entrances (decelerate into place). ease-in for exits. ease-in-out for state changes.
- **GPU-safe**: Only animate `opacity`, `transform`. Never `width`, `height`, `top`, `left`.
- **Respect**: Always check `prefers-reduced-motion`.

## 8. "Wow Factor" Checklist
- [ ] Custom, harmonious color palette (not generic blue/red/green)
- [ ] Premium typography with clear hierarchy
- [ ] Subtle micro-animations on every interactive element
- [ ] Consistent 8px grid spacing
- [ ] Depth through shadows and layering
- [ ] Empty states that delight, not disappoint
- [ ] Loading states that feel alive (skeleton, not spinner)
- [ ] Data that breathes (generous padding around numbers)

## 9. Anti-Patterns (AVOID)
- ❌ All-caps for body text or long labels
- ❌ More than 3 font sizes on a single card
- ❌ Pure black (#000000) or pure white (#ffffff) backgrounds
- ❌ Borders as the only visual separator (use spacing + color too)
- ❌ Animating layout properties (width, height, top, left)
- ❌ Generic placeholder grays — use your brand color at low opacity
- ❌ Inconsistent corner radii on the same page
- ❌ Hover states that only change color (add transform or shadow too)

## Related Skills
- `tailwind-patterns/SKILL.md` — Tailwind implementation of these principles
- `web-design-guidelines/SKILL.md` — Accessibility and performance audit
- `skill-kinetic-ui.md` — Animation and motion philosophy
- `Financial-Information-Architecture.md` — Data-first design constitution
