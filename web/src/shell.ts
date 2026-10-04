import { ROUTES } from './api.ts'
import { avatar, personality } from './avatars.ts'
import { h, icon, replace } from './dom.ts'
import { currentPath, navigate } from './router.ts'
import { state, subscribe } from './state.ts'

export interface Shell {
  root: HTMLElement
  outlet: HTMLElement
  setSection(section: string): void
  destroy(): void
}

const NAV = [
  { section: 'studio', label: 'Studio', href: '#/', icon: 'studio' },
  { section: 'media', label: 'Media', href: '#/media', icon: 'media' },
  { section: 'agents', label: 'Agents', href: '#/agents', icon: 'agents' },
  { section: 'settings', label: 'Settings', href: '#/settings', icon: 'settings' },
] as const

export function createShell(): Shell {
  const navLinks = NAV.map((item) =>
    h(
      'a',
      { class: 'nav-link', href: item.href, 'data-section': item.section },
      icon(item.icon, 18),
      h('span', null, item.label),
    ),
  )

  const projectList = h('ul', { class: 'project-nav', 'aria-label': 'Projects' })
  const readinessDots = h('div', { class: 'sidebar-agents', 'aria-label': 'Agent status' })

  const newProject = h(
    'button',
    { type: 'button', class: 'button button-primary button-block', onclick: () => navigate('/new') },
    icon('plus', 16),
    'New project',
  )

  const sidebar = h(
    'aside',
    { class: 'sidebar', id: 'sidebar', 'aria-label': 'Primary' },
    h(
      'div',
      { class: 'sidebar-head' },
      h('a', { class: 'brand', href: '#/', 'aria-label': 'FrameFusion home' }, brandLockup()),
      h(
        'button',
        {
          type: 'button',
          class: 'icon-button sidebar-close',
          'aria-label': 'Close menu',
          onclick: () => setMenu(false),
        },
        icon('close', 18),
      ),
    ),
    newProject,
    h('nav', { class: 'nav', 'aria-label': 'Main' }, navLinks),
    h(
      'section',
      { class: 'sidebar-section', 'aria-labelledby': 'projects-heading' },
      h('h2', { class: 'sidebar-label', id: 'projects-heading' }, 'Recent projects'),
      projectList,
    ),
    h('div', { class: 'sidebar-foot' }, readinessDots),
  )

  const menuButton = h(
    'button',
    {
      type: 'button',
      class: 'icon-button',
      'aria-label': 'Open menu',
      'aria-controls': 'sidebar',
      'aria-expanded': 'false',
      onclick: () => setMenu(true),
    },
    icon('menu', 20),
  )

  const topbar = h(
    'header',
    { class: 'topbar' },
    menuButton,
    h('a', { class: 'brand', href: '#/', 'aria-label': 'FrameFusion home' }, brandLockup()),
    h(
      'a',
      { class: 'icon-button', href: '#/new', 'aria-label': 'New project' },
      icon('plus', 20),
    ),
  )

  const scrim = h('div', { class: 'scrim', onclick: () => setMenu(false) })
  const outlet = h('main', { class: 'outlet', id: 'main', tabindex: '-1' })
  const root = h(
    'div',
    { class: 'app-shell' },
    h('a', { class: 'skip-link', href: '#main', onclick: skipToMain }, 'Skip to content'),
    topbar,
    sidebar,
    scrim,
    outlet,
  )

  function skipToMain(event: Event): void {
    event.preventDefault()
    outlet.focus()
  }

  function setMenu(open: boolean): void {
    root.classList.toggle('menu-open', open)
    menuButton.setAttribute('aria-expanded', String(open))
    if (open) {
      navLinks[0]?.focus()
    }
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key === 'Escape' && root.classList.contains('menu-open')) {
      setMenu(false)
      menuButton.focus()
    }
  }

  function renderProjects(): void {
    const path = currentPath()
    if (!state.projectsLoaded) {
      replace(projectList, h('li', { class: 'project-nav-empty' }, 'Loading…'))
      return
    }
    if (!state.projects.length) {
      replace(projectList, h('li', { class: 'project-nav-empty' }, 'No projects yet'))
      return
    }
    replace(
      projectList,
      state.projects.slice(0, 15).map((project) => {
        const href = `#/projects/${project.id}`
        const active = path === `/projects/${project.id}`
        return h(
          'li',
          null,
          h(
            'a',
            {
              class: `project-link${active ? ' active' : ''}`,
              href,
              'aria-current': active ? 'page' : null,
              title: project.title,
            },
            project.title,
          ),
        )
      }),
    )
  }

  function renderReadiness(): void {
    const readiness = state.readiness
    if (!readiness) {
      replace(readinessDots)
      return
    }
    const routes = ROUTES.map((route) => readiness[route])
    const blocked = routes.filter((info) => !info.ready)
    const voice = personality(state.app?.personality)
    replace(
      readinessDots,
      h(
        'a',
        {
          class: 'agent-chip',
          href: blocked.length ? '#/settings' : '#/agents',
          title: blocked.length
            ? blocked.map((info) => info.problem).join(' ')
            : routes.map((info) => `${info.name}: ${info.provider_label} · ${info.model}`).join('\n'),
        },
        avatar(voice.id, { size: 'xs', state: blocked.length ? 'setup' : 'idle' }),
        h('span', null, `Orchestrator · ${voice.name}`),
        h('span', { class: `chip-state ${blocked.length ? 'warn' : 'ok'}` }, blocked.length ? 'Set up' : 'Ready'),
      ),
    )
  }

  const unsubscribe = subscribe(() => {
    renderProjects()
    renderReadiness()
  })
  document.addEventListener('keydown', onKey)
  renderProjects()
  renderReadiness()

  return {
    root,
    outlet,
    setSection(section: string) {
      setMenu(false)
      for (const link of navLinks) {
        const active = link.dataset.section === section
        link.classList.toggle('active', active)
        if (active) link.setAttribute('aria-current', 'page')
        else link.removeAttribute('aria-current')
      }
      renderProjects()
    },
    destroy() {
      unsubscribe()
      document.removeEventListener('keydown', onKey)
      root.remove()
    },
  }
}

const SVG_NS = 'http://www.w3.org/2000/svg'

// Same geometry as public/favicon.svg: a red tile, a white F and a hollow blue frame.
const MARK_PARTS: { d?: string; fill: string; rect?: boolean; evenodd?: boolean }[] = [
  { rect: true, fill: '#EF4444' },
  {
    fill: '#3B82F6',
    evenodd: true,
    d: 'M35 30h11a5 5 0 0 1 5 5v11a5 5 0 0 1-5 5H35a5 5 0 0 1-5-5V35a5 5 0 0 1 5-5Zm2.5 6a1.5 1.5 0 0 0-1.5 1.5v6a1.5 1.5 0 0 0 1.5 1.5h6a1.5 1.5 0 0 0 1.5-1.5v-6a1.5 1.5 0 0 0-1.5-1.5Z',
  },
  { fill: '#F8FAFC', d: 'M16 13h30v7H23v7h17v6H23v18h-7Z' },
]

export function brandMark(): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, 'svg')
  svg.setAttribute('viewBox', '0 0 64 64')
  svg.setAttribute('class', 'brand-mark')
  svg.setAttribute('aria-hidden', 'true')
  svg.setAttribute('focusable', 'false')
  for (const part of MARK_PARTS) {
    const el = document.createElementNS(SVG_NS, part.rect ? 'rect' : 'path')
    if (part.rect) {
      el.setAttribute('width', '64')
      el.setAttribute('height', '64')
      el.setAttribute('rx', '16')
    } else {
      el.setAttribute('d', part.d ?? '')
    }
    if (part.evenodd) el.setAttribute('fill-rule', 'evenodd')
    el.setAttribute('fill', part.fill)
    svg.append(el)
  }
  return svg
}

export function brandLockup(): Node[] {
  return [brandMark(), h('span', null, 'Frame', h('span', { class: 'brand-accent' }, 'Fusion'))]
}
