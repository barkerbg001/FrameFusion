import { ROUTES, studio, type MediaAsset, type Project, type ProjectStage, type Readiness, type Route } from '../api.ts'
import emptyProjectsArt from '../assets/illustrations/empty-projects.webp'
import { avatar, personality } from '../avatars.ts'
import { h, icon, relativeTime, replace } from '../dom.ts'
import { navigate } from '../router.ts'
import { refreshProjects, refreshReadiness, state, subscribe, upsertProject } from '../state.ts'
import { toast } from '../toast.ts'
import { errorMessage, errorState, focusHeading, illustration, loadingState, pageHeader } from './common.ts'
import { mediaThumb } from './media.ts'

const STARTERS = [
  'A 30-second explainer on why octopuses have three hearts',
  'A calm narrated short about the first photo of a black hole',
  'Three hook ideas for a video on the history of coffee',
]

export function dashboardView(outlet: HTMLElement): () => void {
  const agents = h('section', { class: 'agent-cards', 'aria-label': 'Your agents' })
  const projectsBody = h('div', { class: 'projects-body' })
  const mediaBody = h('div', { class: 'recent-media' })

  const quickInput = h('textarea', {
    id: 'quick-start',
    class: 'quick-input',
    rows: 2,
    maxlength: 8000,
    placeholder: 'Describe a video idea to start a new project…',
  })
  const quickButton = h(
    'button',
    { type: 'submit', class: 'button button-primary' },
    icon('send', 16),
    'Start project',
  )
  const quickForm = h(
    'form',
    { class: 'quick-start' },
    h('label', { for: 'quick-start', class: 'sr-only' }, 'Video idea'),
    quickInput,
    h(
      'div',
      { class: 'quick-row' },
      h(
        'div',
        { class: 'starter-list' },
        STARTERS.map((text) =>
          h(
            'button',
            {
              type: 'button',
              class: 'chip',
              onclick: () => {
                quickInput.value = text
                quickInput.focus()
              },
            },
            text,
          ),
        ),
      ),
      quickButton,
    ),
  )

  quickForm.addEventListener('submit', async (event) => {
    event.preventDefault()
    const idea = quickInput.value.trim()
    if (!idea) {
      quickInput.focus()
      return
    }
    quickButton.disabled = true
    try {
      const project = await studio.createProject()
      upsertProject(project)
      sessionStorage.setItem(`framefusion:draft:${project.id}`, idea)
      navigate(`/projects/${project.id}`)
    } catch (error) {
      toast(errorMessage(error), 'error')
      quickButton.disabled = false
    }
  })

  replace(
    outlet,
    h(
      'div',
      { class: 'page page-dashboard' },
      pageHeader(
        'Studio',
        'Start a project and talk it through with the orchestrator. It plans the video, finds real images and renders it when you ask.',
      ),
      quickForm,
      agents,
      h(
        'section',
        { class: 'section', 'aria-labelledby': 'projects-title' },
        h(
          'div',
          { class: 'section-head' },
          h('h2', { id: 'projects-title' }, 'Projects'),
        ),
        projectsBody,
      ),
      h(
        'section',
        { class: 'section', 'aria-labelledby': 'media-title' },
        h(
          'div',
          { class: 'section-head' },
          h('h2', { id: 'media-title' }, 'Recent media'),
          h('a', { class: 'link', href: '#/media' }, 'View all', icon('chevron', 14)),
        ),
        mediaBody,
      ),
    ),
  )
  focusHeading(outlet)

  function renderAgents(): void {
    const readiness = state.readiness
    if (!readiness) {
      replace(agents, loadingState('Checking agents…'))
      return
    }
    replace(agents, orchestratorCard(readiness))
  }

  function renderProjects(): void {
    if (!state.projectsLoaded) {
      replace(projectsBody, loadingState('Loading projects…'))
      return
    }
    if (!state.projects.length) {
      replace(
        projectsBody,
        h(
          'div',
          { class: 'empty-hero' },
          illustration(emptyProjectsArt),
          h('h2', null, 'Your first short starts with an idea'),
          h('p', null, 'Describe it above and the orchestrator will help you shape the script, or open an empty project and talk it through first.'),
          h('a', { class: 'button', href: '#/new' }, icon('plus', 16), 'New empty project'),
        ),
      )
      return
    }
    const groups = STAGES.map((stage) => ({
      ...stage,
      projects: state.projects.filter((project) => stageOf(project) === stage.id),
    })).filter((group) => group.projects.length)
    replace(
      projectsBody,
      h(
        'div',
        { class: 'stage-groups' },
        groups.map((group) =>
          h(
            'section',
            { class: `stage-group stage-${group.id}`, 'aria-labelledby': `stage-${group.id}-title` },
            h(
              'div',
              { class: 'stage-head' },
              h('span', { class: 'stage-dot', 'aria-hidden': 'true' }),
              h('h3', { id: `stage-${group.id}-title` }, group.label),
              h('span', { class: 'stage-count' }, String(group.projects.length)),
              h('span', { class: 'muted' }, `· ${group.hint}`),
            ),
            h('ul', { class: 'project-grid' }, group.projects.map((project) => h('li', null, projectCard(project)))),
          ),
        ),
      ),
    )
  }

  async function loadMedia(): Promise<void> {
    replace(mediaBody, loadingState('Loading media…'))
    try {
      const media = await studio.media()
      renderMedia(media.slice(0, 6))
    } catch (error) {
      replace(mediaBody, errorState(error, () => void loadMedia()))
    }
  }

  function renderMedia(media: MediaAsset[]): void {
    if (!media.length) {
      replace(
        mediaBody,
        h('p', { class: 'muted' }, 'Videos and audio created in your projects will appear here.'),
      )
      return
    }
    replace(mediaBody, h('ul', { class: 'media-strip' }, media.map((asset) => h('li', null, mediaThumb(asset)))))
  }

  const unsubscribe = subscribe(() => {
    renderAgents()
    renderProjects()
  })
  renderAgents()
  renderProjects()
  void refreshProjects().catch((error) => replace(projectsBody, errorState(error, () => void refreshProjects())))
  void refreshReadiness().catch(() => replace(agents))
  void loadMedia()

  return unsubscribe
}

const STAGES: { id: ProjectStage; label: string; hint: string }[] = [
  { id: 'needs_attention', label: 'Needs attention', hint: 'the last job failed' },
  { id: 'in_production', label: 'In production', hint: 'a job is running' },
  { id: 'developing', label: 'Developing', hint: 'script and planning' },
  { id: 'idea', label: 'Ideas', hint: 'not started yet' },
  { id: 'delivered', label: 'Delivered', hint: 'has a final video' },
]

function stageOf(project: Project): ProjectStage {
  return project.stage ?? (project.message_count ? 'developing' : 'idea')
}

function projectCard(project: Project): HTMLElement {
  return h(
    'a',
    { class: 'project-card', href: `#/projects/${project.id}` },
    h('h3', null, project.title),
    h('p', { class: 'project-snippet' }, project.last_message || 'No messages yet'),
    h(
      'p',
      { class: 'project-meta' },
      h('span', null, relativeTime(project.updated_at)),
      project.message_count ? h('span', null, `${project.message_count} message${project.message_count === 1 ? '' : 's'}`) : null,
      project.video_count
        ? h('span', { class: 'project-stage' }, icon('film', 12), `${project.video_count} video${project.video_count === 1 ? '' : 's'}`)
        : project.media_count
          ? h('span', null, `${project.media_count} file${project.media_count === 1 ? '' : 's'}`)
          : null,
    ),
  )
}

function orchestratorCard(readiness: Record<Route, Readiness>): HTMLElement {
  const voice = personality(state.app?.personality)
  const ready = ROUTES.every((route) => readiness[route].ready)
  return h(
    'article',
    { class: `agent-card agent-card-${voice.tone}` },
    avatar(voice.id, { size: 'lg', state: ready ? 'idle' : 'setup', portrait: true }),
    h(
      'div',
      { class: 'agent-card-body' },
      h('h2', null, 'Orchestrator', h('span', { class: 'role-tag' }, voice.name)),
      h(
        'p',
        null,
        `${voice.summary} It leads the research, script and visual specialists, checks their work and renders the video.`,
      ),
      ROUTES.map((route) => {
        const info = readiness[route]
        return info.ready
          ? h(
              'p',
              { class: 'agent-route' },
              h('span', { class: 'status-dot ok', 'aria-hidden': 'true' }),
              h('span', null, `${info.name}: ${info.provider_label} · `),
              h('code', null, info.model ?? ''),
            )
          : h(
              'p',
              { class: 'agent-route warn' },
              h('span', { class: 'status-dot warn', 'aria-hidden': 'true' }),
              h('span', null, `${info.name}: ${info.problem ?? 'Not set up'}`),
              ' ',
              h('a', { href: '#/settings', class: 'link' }, 'Set up'),
            )
      }),
      h('a', { class: 'link', href: '#/settings/personality' }, 'Change personality', icon('chevron', 14)),
    ),
  )
}
