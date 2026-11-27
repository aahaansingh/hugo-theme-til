/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./layouts/**/*.html', './assets/ts/**/*.ts'],
  plugins: [require('@tailwindcss/typography')],
  // classes that only appear in generated/third-party markup: chroma (code), Waline (comments)
  safelist: ['chroma', 'wl-count', 'wl-sort', 'wl-meta', 'wl-rss', 'wl-header', 'wl-header-item', 'wl-panel', 'wl-editor', 'wl-footer', 'wl-btn', 'wl-comment', 'wl-login-info', 'wl-login-nick']
};
