import type { Config } from 'tailwindcss'
import animate from 'tailwindcss-animate'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: 'rgb(var(--bg-rgb) / <alpha-value>)',
        surface: 'rgb(var(--surface-rgb) / <alpha-value>)',
        raised: 'rgb(var(--raised-rgb) / <alpha-value>)',
        line: 'rgb(var(--line-rgb) / <alpha-value>)',
        pink: {
          DEFAULT: 'rgb(var(--pink-rgb) / <alpha-value>)',
          soft: 'rgb(var(--pink-soft-rgb) / <alpha-value>)',
          dim: 'var(--pink-dim)',
        },
        muted: 'rgb(var(--muted-rgb) / <alpha-value>)',
        fg: 'rgb(var(--fg-rgb) / <alpha-value>)',
      },
      fontFamily: {
        display: ['"Bricolage Grotesque"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      transitionDuration: { 400: '400ms' },
      boxShadow: {
        glow: '0 0 24px rgba(255,46,147,0.35)',
        'glow-lg': '0 0 48px rgba(255,46,147,0.45)',
      },
    },
  },
  plugins: [animate],
} satisfies Config
