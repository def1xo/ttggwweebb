import React from 'react'


const ThemeToggle: React.FC = () => {
const anyWindow: any = window
const webapp = anyWindow.Telegram?.WebApp
const scheme = webapp?.colorScheme || 'light'
// this component is mostly visual given Telegram manages scheme; provide manual fallback
return (
<button className="px-2 py-1 border rounded">{scheme === 'dark' ? '🌙' : '☀️'}</button>
)
}
export default ThemeToggle