import type { Theme } from './api.ts'

// The saved preference lives on the server; this cache only prevents a flash of the
// wrong theme before the session loads. It never holds anything sensitive.
const CACHE_KEY = 'framefusion:theme'
const media = window.matchMedia('(prefers-color-scheme: light)')
let current: Theme = readCached()

function readCached(): Theme {
  try {
    const value = localStorage.getItem(CACHE_KEY)
    return value === 'dark' || value === 'light' || value === 'system' ? value : 'system'
  } catch {
    return 'system'
  }
}

function resolved(theme: Theme): 'dark' | 'light' {
  if (theme === 'system') return media.matches ? 'light' : 'dark'
  return theme
}

function paint(): void {
  const mode = resolved(current)
  document.documentElement.dataset.theme = mode
  document.documentElement.style.colorScheme = mode
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (meta) meta.content = mode === 'light' ? '#f5f7fa' : '#090b10'
}

export function applyTheme(theme: Theme): void {
  current = theme
  try {
    localStorage.setItem(CACHE_KEY, theme)
  } catch {
    // Private mode: the server copy still applies on next load.
  }
  paint()
}

export function currentTheme(): Theme {
  return current
}

media.addEventListener('change', () => {
  if (current === 'system') paint()
})

paint()
