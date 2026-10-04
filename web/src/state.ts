import {
  app,
  studio,
  type AppState,
  type MediaServiceName,
  type IntegrationStatus,
  type Route,
  type Project,
  type Readiness,
} from './api.ts'

type Listener = () => void

// Small shared store for data the shell and several views need.
export const state = {
  app: null as AppState | null,
  projects: [] as Project[],
  projectsLoaded: false,
  readiness: null as Record<Route, Readiness> | null,
  integrations: null as Record<MediaServiceName, IntegrationStatus> | null,
}

const listeners = new Set<Listener>()

export function subscribe(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function notify(): void {
  for (const listener of listeners) listener()
}

export function setAppState(next: AppState): void {
  state.app = next
  state.readiness = next.readiness
  state.integrations = next.integrations
  notify()
}

// Re-reads readiness, integrations and onboarding after a settings change.
export async function refreshApp(): Promise<AppState> {
  const next = await app.get()
  setAppState(next)
  return next
}

export async function refreshProjects(): Promise<void> {
  state.projects = await studio.projects()
  state.projectsLoaded = true
  notify()
}

export async function refreshReadiness(): Promise<Record<Route, Readiness>> {
  const next = await refreshApp()
  return next.readiness
}

export function upsertProject(project: Project): void {
  const index = state.projects.findIndex((p) => p.id === project.id)
  if (index >= 0) {
    state.projects[index] = { ...state.projects[index]!, ...project }
  } else {
    state.projects.unshift(project)
  }
  state.projects.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  notify()
}

export function removeProject(id: string): void {
  state.projects = state.projects.filter((p) => p.id !== id)
  notify()
}
