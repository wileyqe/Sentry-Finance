/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Tokens wrap var(--*) in color-mix so Tailwind's /<alpha-value>
        // modifier produces valid CSS (e.g. `bg-primary/10` →
        // `color-mix(in oklch, var(--primary) 10%, transparent)`). Without
        // this wrapper the modifier silently compiles to transparent on
        // OKLch custom-property-bound colors.
        primary: {
          DEFAULT: "color-mix(in oklch, var(--primary) calc(<alpha-value> * 100%), transparent)",
          foreground: "color-mix(in oklch, var(--primary-foreground) calc(<alpha-value> * 100%), transparent)",
        },
        background: "color-mix(in oklch, var(--background) calc(<alpha-value> * 100%), transparent)",
        foreground: "color-mix(in oklch, var(--foreground) calc(<alpha-value> * 100%), transparent)",
        border: "color-mix(in oklch, var(--border) calc(<alpha-value> * 100%), transparent)",
        input: "color-mix(in oklch, var(--input) calc(<alpha-value> * 100%), transparent)",
        ring: "color-mix(in oklch, var(--ring) calc(<alpha-value> * 100%), transparent)",
        card: {
          DEFAULT: "color-mix(in oklch, var(--card) calc(<alpha-value> * 100%), transparent)",
          foreground: "color-mix(in oklch, var(--card-foreground) calc(<alpha-value> * 100%), transparent)",
        },
        popover: {
          DEFAULT: "color-mix(in oklch, var(--popover) calc(<alpha-value> * 100%), transparent)",
          foreground: "color-mix(in oklch, var(--popover-foreground) calc(<alpha-value> * 100%), transparent)",
        },
        secondary: {
          DEFAULT: "color-mix(in oklch, var(--secondary) calc(<alpha-value> * 100%), transparent)",
          foreground: "color-mix(in oklch, var(--secondary-foreground) calc(<alpha-value> * 100%), transparent)",
        },
        muted: {
          DEFAULT: "color-mix(in oklch, var(--muted) calc(<alpha-value> * 100%), transparent)",
          foreground: "color-mix(in oklch, var(--muted-foreground) calc(<alpha-value> * 100%), transparent)",
        },
        accent: {
          DEFAULT: "color-mix(in oklch, var(--accent) calc(<alpha-value> * 100%), transparent)",
          foreground: "color-mix(in oklch, var(--accent-foreground) calc(<alpha-value> * 100%), transparent)",
        },
        destructive: {
          DEFAULT: "color-mix(in oklch, var(--destructive) calc(<alpha-value> * 100%), transparent)",
          foreground: "color-mix(in oklch, var(--destructive-foreground) calc(<alpha-value> * 100%), transparent)",
        },
        "surface-raised": "color-mix(in oklch, var(--surface-raised) calc(<alpha-value> * 100%), transparent)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans:    ["'Inter Variable'", "system-ui", "-apple-system", "sans-serif"],
        display: ["'Newsreader Variable'", "Georgia", "'Times New Roman'", "serif"],
        mono:    ["'JetBrains Mono Variable'", "ui-monospace", "'SF Mono'", "Menlo", "monospace"],
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}

