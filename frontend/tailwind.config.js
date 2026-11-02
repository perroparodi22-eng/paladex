/** Parodi Group design tokens — deep forest green, warm ivory, muted gold, charcoal. */
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        forest: {
          950: '#0A1F17', 900: '#0E2A1F', 800: '#143A2B', 700: '#1B4A37', 600: '#24604A',
          500: '#3A7A60', 300: '#8FB5A2', 100: '#E3ECE6', 50: '#F1F5F2',
        },
        ivory: { DEFAULT: '#F6F1E4', deep: '#EDE5D0' },
        paper: '#FBF9F3',
        gold: { DEFAULT: '#A8873A', light: '#C9A85A', pale: '#F1E7CC', dark: '#7D6428' },
        charcoal: { DEFAULT: '#1F2120', soft: '#2B2D2A' },
        line: { DEFAULT: '#DDD6C4', soft: '#E9E3D3' },
        muted: '#6B6A62',
        up: '#2E7D4F',
        down: '#A33A2A',
        warn: '#B7791F',
      },
      fontFamily: {
        serif: ['"Source Serif 4"', 'Georgia', 'serif'],
        sans: ['Inter', 'system-ui', 'Segoe UI', 'Arial', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'Consolas', 'monospace'],
      },
      borderRadius: { DEFAULT: '3px', sm: '2px', md: '4px' },
      boxShadow: { panel: '0 1px 0 rgba(31,33,32,0.04)' },
    },
  },
  plugins: [],
}
