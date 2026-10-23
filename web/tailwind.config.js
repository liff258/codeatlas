/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // 纸张感底色：偏暖的白，长时间阅读不刺眼
        paper: {
          50: '#fbfaf8',
          100: '#f6f4f0',
          200: '#eeeae3',
          300: '#e2ddd4',
        },
        ink: {
          900: '#171614',
          700: '#3a3733',
          500: '#6b665e',
          400: '#8f8981',
        },
        line: '#e4dfd6',
        // 两个学科域的主色，全局唯一的高饱和来源
        backend: '#2563eb',
        ai: '#db2777',
        common: '#64748b',
        // 跨域边专用：琥珀色，在图上必须一眼看到
        bridge: '#d97706',
      },
      fontFamily: {
        sans: [
          '"Inter var"', 'Inter', '-apple-system', 'BlinkMacSystemFont',
          '"Segoe UI"', '"PingFang SC"', '"Hiragino Sans GB"',
          '"Microsoft YaHei"', 'sans-serif',
        ],
        serif: ['"Source Serif 4"', 'Georgia', '"Songti SC"', 'serif'],
        mono: ['"JetBrains Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(23,22,20,.04), 0 4px 16px -4px rgba(23,22,20,.06)',
        lift: '0 2px 4px rgba(23,22,20,.05), 0 12px 32px -8px rgba(23,22,20,.10)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        caret: {
          '0%, 45%': { opacity: '1' },
          '50%, 95%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'pulse-ring': {
          '0%': { transform: 'scale(.9)', opacity: '.7' },
          '70%': { transform: 'scale(1.4)', opacity: '0' },
          '100%': { transform: 'scale(1.4)', opacity: '0' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'fade-up': 'fade-up .28s cubic-bezier(.22,1,.36,1) both',
        caret: 'caret 1.1s step-end infinite',
        'pulse-ring': 'pulse-ring 1.6s cubic-bezier(.22,1,.36,1) infinite',
        shimmer: 'shimmer 1.6s infinite',
      },
    },
  },
  plugins: [],
}
