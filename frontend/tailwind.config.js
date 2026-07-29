import tailwindcssAnimate from "tailwindcss-animate";

/**
 * Tailwind maps semantic token names onto the CSS custom properties in index.css.
 * Components write `bg-surface` and `text-ink`, never `bg-slate-900` — so retheming
 * touches one file and dark mode is not a per-component concern.
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "rgb(var(--surface) / <alpha-value>)",
          sunken: "rgb(var(--surface-sunken) / <alpha-value>)",
          raised: "rgb(var(--surface-raised) / <alpha-value>)",
          hover: "rgb(var(--surface-hover) / <alpha-value>)",
          active: "rgb(var(--surface-active) / <alpha-value>)",
        },
        ink: {
          DEFAULT: "rgb(var(--ink) / <alpha-value>)",
          secondary: "rgb(var(--ink-secondary) / <alpha-value>)",
          muted: "rgb(var(--ink-muted) / <alpha-value>)",
          inverse: "rgb(var(--ink-inverse) / <alpha-value>)",
        },
        line: {
          DEFAULT: "rgb(var(--line) / <alpha-value>)",
          strong: "rgb(var(--line-strong) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          hover: "rgb(var(--accent-hover) / <alpha-value>)",
          subtle: "rgb(var(--accent-subtle) / <alpha-value>)",
          ink: "rgb(var(--accent-ink) / <alpha-value>)",
        },
        danger: {
          DEFAULT: "rgb(var(--danger) / <alpha-value>)",
          subtle: "rgb(var(--danger-subtle) / <alpha-value>)",
        },
        success: "rgb(var(--success) / <alpha-value>)",
        warning: "rgb(var(--warning) / <alpha-value>)",
        series: {
          1: "rgb(var(--series-1) / <alpha-value>)",
          2: "rgb(var(--series-2) / <alpha-value>)",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 4px)",
        sm: "calc(var(--radius) - 6px)",
      },
      fontSize: {
        // A restrained scale. A size outside it signals the hierarchy is wrong.
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
        xs: ["0.75rem", { lineHeight: "1.125rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.875rem", { lineHeight: "1.5rem" }],
        md: ["0.9375rem", { lineHeight: "1.625rem" }],
        lg: ["1.0625rem", { lineHeight: "1.75rem" }],
        xl: ["1.375rem", { lineHeight: "1.875rem", letterSpacing: "-0.01em" }],
        "2xl": ["1.75rem", { lineHeight: "2.25rem", letterSpacing: "-0.02em" }],
      },
      boxShadow: {
        // Depth comes from surface steps; shadows stay subtle.
        raised: "0 1px 2px 0 rgb(0 0 0 / 0.06), 0 1px 3px 1px rgb(0 0 0 / 0.04)",
        overlay: "0 4px 8px 3px rgb(0 0 0 / 0.08), 0 1px 3px rgb(0 0 0 / 0.10)",
      },
      keyframes: {
        "fade-in-up": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in-up": "fade-in-up 180ms ease-out",
      },
    },
  },
  plugins: [tailwindcssAnimate],
};
