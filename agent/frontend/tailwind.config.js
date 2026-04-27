/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        mc: {
          dark: '#1a1a2e',
          panel: '#16213e',
          accent: '#0f3460',
          gold: '#e4a018',
          green: '#55ff55',
          red: '#ff5555',
          aqua: '#55ffff',
          purple: '#aa00ff',
          gray: '#aaaaaa',
        },
      },
    },
  },
  plugins: [],
}
