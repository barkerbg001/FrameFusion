import './styles/tokens.css'
import './styles/app.css'
import { studio } from './api.ts'
import { h, replace } from './dom.ts'
import { currentPath, match, navigate, route, type Cleanup } from './router.ts'
import { createShell, type Shell } from './shell.ts'
import { refreshApp, refreshProjects, state, upsertProject } from './state.ts'
import { applyTheme } from './theme.ts'
import { toast } from './toast.ts'
import { agentsView } from './views/agents.ts'
import { errorMessage, errorState, loadingState } from './views/common.ts'
import { dashboardView } from './views/dashboard.ts'
import { mediaView } from './views/media.ts'
import { renderOnboarding } from './views/onboarding.ts'
import { projectView } from './views/project.ts'
import { settingsView } from './views/settings.ts'

const ONBOARDING = '/onboarding'
const root = document.querySelector<HTMLElement>('#app')!
let shell: Shell | null = null
let cleanup: Cleanup | null = null

route('/', 'studio', dashboardView)
route('/projects/:id', 'studio', projectView)
route('/media', 'media', mediaView)
route('/agents', 'agents', agentsView)
route('/settings', 'settings', settingsView)
route('/settings/:section', 'settings', settingsView)
route('/new', 'studio', (outlet) => {
  replace(outlet, h('div', { class: 'page' }, loadingState('Creating project…')))
  studio
    .createProject()
    .then((project) => {
      upsertProject(project)
      window.location.replace(`#/projects/${project.id}`)
    })
    .catch((error) => {
      toast(errorMessage(error), 'error')
      window.location.replace('#/')
    })
})

function teardown(): void {
  cleanup?.()
  cleanup = null
}

function render(): void {
  if (!state.app) return
  teardown()
  const path = currentPath()

  if (path === ONBOARDING) {
    shell?.destroy()
    shell = null
    document.title = 'Set up · FrameFusion'
    cleanup = renderOnboarding(root, (target) => navigate(target))
    return
  }
  if (!state.app.onboarding.completed) {
    navigate(ONBOARDING)
    return
  }

  if (!shell) {
    shell = createShell()
    replace(root, shell.root)
    void refreshProjects().catch(() => {})
  }
  const found = match(path)
  if (!found) {
    navigate('/')
    return
  }
  shell.setSection(found.route.section)
  document.title = 'FrameFusion'
  window.scrollTo(0, 0)
  cleanup = found.route.view(shell.outlet, found.params) ?? null
}

window.addEventListener('hashchange', render)

async function boot(): Promise<void> {
  replace(root, h('div', { class: 'boot' }, loadingState('Starting FrameFusion…')))
  try {
    const appState = await refreshApp()
    applyTheme(appState.theme)
    render()
  } catch (error) {
    replace(root, h('div', { class: 'boot' }, errorState(error, () => void boot())))
  }
}

void boot()
