import { Link, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'

export default function Navbar({ user, onLogout }) {
  const { pathname } = useLocation()
  const [dark, setDark] = useState(() => {
    return localStorage.getItem('theme') === 'dark' ||
      (!localStorage.getItem('theme') && window.matchMedia('(prefers-color-scheme: dark)').matches)
  })

  useEffect(() => {
    if (dark) {
      document.documentElement.classList.add('dark')
      localStorage.setItem('theme', 'dark')
    } else {
      document.documentElement.classList.remove('dark')
      localStorage.setItem('theme', 'light')
    }
  }, [dark])

  const navLink = (to, label) => (
    <Link
      to={to}
      className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
        pathname === to
          ? 'bg-indigo-600 text-white'
          : 'text-gray-600 dark:text-gray-300 hover:text-indigo-600 dark:hover:text-indigo-400'
      }`}
    >
      {label}
    </Link>
  )

  return (
    <nav className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-6 py-3 flex items-center justify-between">
      <span className="text-lg font-bold text-indigo-600 dark:text-indigo-400">SOP Assistant</span>

      {user && (
        <div className="flex items-center gap-4">
          {navLink('/documents', 'Documents')}
          {navLink('/chat', 'Chat')}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={() => setDark(d => !d)}
          className="text-gray-500 dark:text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors text-sm"
          title="Toggle dark mode"
        >
          {dark ? '☀️' : '🌙'}
        </button>

        {user && (
          <>
            <span className="text-sm text-gray-500 dark:text-gray-400 hidden sm:inline">
              {user.email}
            </span>
            <button
              onClick={onLogout}
              className="text-sm text-red-500 hover:text-red-600 dark:hover:text-red-400 transition-colors"
            >
              Logout
            </button>
          </>
        )}
      </div>
    </nav>
  )
}
