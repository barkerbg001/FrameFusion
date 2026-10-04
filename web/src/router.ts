export type Cleanup = () => void
export type View = (outlet: HTMLElement, params: Record<string, string>) => Cleanup | void

interface Route {
  pattern: RegExp
  keys: string[]
  view: View
  section: string
}

const routes: Route[] = []

export function route(path: string, section: string, view: View): void {
  const keys: string[] = []
  const pattern = new RegExp(
    `^${path.replace(/:(\w+)/g, (_, key: string) => {
      keys.push(key)
      return '([^/]+)'
    })}/?$`,
  )
  routes.push({ pattern, keys, view, section })
}

export function currentPath(): string {
  const hash = window.location.hash.replace(/^#/, '')
  return hash.startsWith('/') ? hash.split('?')[0]! : '/'
}

export function navigate(path: string): void {
  if (currentPath() === path) {
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  } else {
    window.location.hash = path
  }
}

export function match(path: string): { route: Route; params: Record<string, string> } | null {
  for (const candidate of routes) {
    const found = candidate.pattern.exec(path)
    if (found) {
      const params: Record<string, string> = {}
      candidate.keys.forEach((key, i) => {
        params[key] = decodeURIComponent(found[i + 1] ?? '')
      })
      return { route: candidate, params }
    }
  }
  return null
}
