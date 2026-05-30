import { NavLink, Outlet } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { API_BASE, checkHealth, type ApiStatus } from '../lib/api'

export function Layout() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')

  useEffect(() => {
    let cancelled = false
    checkHealth()
      .then(() => {
        if (!cancelled) setApiStatus('online')
      })
      .catch(() => {
        if (!cancelled) setApiStatus('offline')
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="shell">
      <header className="shell__header">
        <div>
          <p className="eyebrow">FrameFusion</p>
          <h1>Video studio</h1>
          <p className="subtitle">Generate lofi loops, slideshows, and shorts from your media.</p>
        </div>
        <div className={`status status--${apiStatus}`}>
          {apiStatus === 'checking' && 'Checking API…'}
          {apiStatus === 'online' && 'API connected'}
          {apiStatus === 'offline' && 'API offline'}
        </div>
      </header>

      {apiStatus === 'offline' && (
        <p className="banner banner--error">
          Cannot reach the API at{' '}
          <code>{API_BASE || 'http://localhost:8000 (via Vite proxy)'}</code>.
        </p>
      )}

      <nav className="nav">
        <NavLink to="/" end>Dashboard</NavLink>
        <NavLink to="/lofi">Lofi</NavLink>
        <NavLink to="/slideshow">Slideshow</NavLink>
        <NavLink to="/shorts">Shorts</NavLink>
        <NavLink to="/settings">Settings</NavLink>
      </nav>

      <main className="shell__main">
        <Outlet context={{ apiStatus }} />
      </main>
    </div>
  )
}

export type LayoutContext = {
  apiStatus: ApiStatus
}
