import {
  ApiError,
  isTerminal,
  narration,
  ROUTES,
  studio,
  type ChatMessage,
  type EdgeVoice,
  type Job,
  type JobEvent,
  type MediaAsset,
  type ImageAssessment,
  type ImageCheckResult,
  type ImageDecision,
  type ImageSearchResult,
  type ImageSearchSource,
  type ImageVerification,
  type NarrationProvider,
  type PersonalityId,
  type ProductionOptions,
  type ProductionState,
  type ProductionTask,
  type ProjectDetail,
  type Route,
  type SceneState,
  type SearchedImage,
  type SceneVisualState,
  type SceneVisualStatus,
  type Stage,
  type TaskStatus,
  type VisualBrief,
} from '../api.ts'
import { avatar, personality, PERSONALITIES, PERSONALITY_IDS, type AvatarState } from '../avatars.ts'
import { h, icon, relativeTime, replace, spinner } from '../dom.ts'
import { watchJob, type JobWatcher } from '../jobs.ts'
import { renderMarkdown } from '../markdown.ts'
import { navigate } from '../router.ts'
import { refreshApp, refreshProjects, refreshReadiness, removeProject, state, upsertProject } from '../state.ts'
import { toast } from '../toast.ts'
import {
  confirmDialog,
  effectiveNarration,
  errorGuidance,
  errorMessage,
  errorState,
  integrationHint,
  loadingState,
  settingsHref,
  setupNotice,
} from './common.ts'
import { edgeVoiceMeta, loadEdgeVoices, narrationSummary } from './integrations.ts'
import { attachmentView, mediaThumb } from './media.ts'

/** Production stages in order, and who does each one for the orchestrator. */
const STAGES: { id: Stage; label: string; owner: string; glyph: string }[] = [
  { id: 'brief', label: 'Creative brief', owner: 'Orchestrator', glyph: 'idea' },
  { id: 'research', label: 'Research', owner: 'Research specialist', glyph: 'research' },
  { id: 'script', label: 'Script and scenes', owner: 'Script specialist', glyph: 'script' },
  { id: 'visuals', label: 'Scene images', owner: 'Visual specialist', glyph: 'image' },
  { id: 'narration', label: 'Narration', owner: 'Narration service', glyph: 'voice' },
  { id: 'music', label: 'Music bed', owner: 'Music service', glyph: 'music' },
  { id: 'render', label: 'Render', owner: 'Timeline renderer', glyph: 'film' },
  { id: 'qc', label: 'Quality check', owner: 'Quality check service', glyph: 'shield' },
]

const SPECIALIST_NAMES: Record<string, string> = {
  research: 'Research specialist',
  script: 'Script specialist',
  visual: 'Visual specialist',
  ideas: 'Ideas specialist',
  music_composer: 'Music specialist',
  narration: 'Narration service',
  music: 'Music service',
  renderer: 'Timeline renderer',
  qc: 'Quality check service',
}

function specialistName(agent: string): string {
  return SPECIALIST_NAMES[agent] ?? agent.replace(/_/g, ' ')
}

type StepState = TaskStatus | 'pending'

const STEP_LABEL: Record<StepState, string> = {
  pending: 'not started',
  proposed: 'planned',
  active: 'working',
  completed: 'done, unchecked',
  verified: 'verified',
  failed: 'failed',
  cancelled: 'cancelled',
  skipped: 'skipped',
  invalidated: 'needs redo',
}

const STEP_VISUAL: Record<StepState, 'pending' | 'running' | 'done' | 'failed'> = {
  pending: 'pending',
  proposed: 'pending',
  active: 'running',
  completed: 'done',
  verified: 'done',
  failed: 'failed',
  cancelled: 'pending',
  skipped: 'pending',
  invalidated: 'pending',
}

const EVENT_STEP: Record<string, StepState> = {
  running: 'active',
  done: 'verified',
  reused: 'verified',
  failed: 'failed',
  cancelled: 'cancelled',
  skipped: 'skipped',
}

const RIGHTS_LABEL = { documented: 'Licence recorded', unknown: 'Rights unknown' } as const

const SCENE_STATUS: Record<SceneVisualStatus, { label: string; tone: '' | 'tag-ok' | 'tag-warn' | 'tag-danger' }> = {
  searching: { label: 'Searching', tone: '' },
  candidates_found: { label: 'Candidates found', tone: '' },
  awaiting_review: { label: 'Awaiting your review', tone: 'tag-warn' },
  selected: { label: 'Image selected', tone: 'tag-ok' },
  no_suitable_result: { label: 'No suitable image found', tone: 'tag-warn' },
  download_failed: { label: 'Download failed', tone: 'tag-danger' },
  title_card: { label: 'Title card', tone: '' },
}

const DECISION_LABEL: Record<ImageDecision, string> = {
  accept: 'Matches the brief',
  review: 'Needs your review',
  illustrative: 'Illustrative only',
  reject: 'Rejected',
}

const VERIFICATION_LABEL: Record<ImageVerification, string> = {
  vision: 'Visually checked',
  metadata: 'Visually unverified',
  none: 'Not checked',
  user: 'Chosen by you',
}

const SPECIFICITY_LABEL: Record<VisualBrief['specificity'], string> = {
  exact: 'That exact subject',
  representative: 'A representative example',
  generic: 'Any good example',
}

const SOURCE_NAME: Record<string, string> = {
  auto: 'licensed sources',
  pexels: 'Pexels',
  pixabay: 'Pixabay',
  wikimedia: 'Wikimedia Commons',
  openverse: 'Openverse',
  brave: 'Brave web search',
  url: 'your link',
  webpage: 'your webpage',
  link: 'your link',
  upload: 'your upload',
}

const GOOGLE_IMAGES_SEARCH = 'https://www.google.com/search?udm=2&q='

const JOB_TITLE: Record<Job['kind'], string> = {
  production: 'Production run',
  chat: 'Chat reply',
  agent: 'Agent run',
  render: 'Render',
  narration: 'Narration retry',
  image_check: 'Image check',
}

const PROVIDER_NAME: Record<NarrationProvider, string> = { edge: 'Edge TTS', elevenlabs: 'ElevenLabs' }

type PanelTab = 'activity' | 'scenes' | 'narration' | 'exports'

const STATUS_LABEL: Record<string, string> = {
  queued: 'Queued',
  running: 'Working',
  succeeded: 'Finished',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

type Mode = 'chat' | 'production'

export function projectView(outlet: HTMLElement, params: Record<string, string>): () => void {
  const projectId = params.id!
  let detail: ProjectDetail | null = null
  let job: Job | null = null
  let events: JobEvent[] = []
  let watcher: JobWatcher | null = null
  let mode: Mode = 'chat'
  let disposed = false
  let tick = 0

  // --- Static structure --------------------------------------------------------------

  const titleSlot = h('div', { class: 'project-title' })
  const panelToggle = h(
    'button',
    {
      type: 'button',
      class: 'button button-ghost panel-toggle',
      'aria-controls': 'activity-panel',
      'aria-expanded': 'false',
      onclick: () => setPanel(!page.classList.contains('panel-open')),
    },
    icon('agents', 16),
    'Activity',
  )
  const deleteButton = h(
    'button',
    {
      type: 'button',
      class: 'icon-button danger',
      'aria-label': 'Delete project',
      title: 'Delete project',
      onclick: () => void deleteProject(),
    },
    icon('trash', 18),
  )

  const thread = h('div', { class: 'thread', role: 'log', 'aria-live': 'polite', 'aria-relevant': 'additions', tabindex: '0', 'aria-label': 'Conversation' })
  const notice = h('div', { class: 'composer-notice' })

  const input = h('textarea', {
    id: 'composer-input',
    class: 'composer-input',
    rows: 1,
    maxlength: 8000,
    placeholder: 'Message the orchestrator…',
  })
  const formatSelect = h(
    'select',
    { id: 'production-format' },
    h('option', { value: 'auto' }, 'Let the orchestrator choose'),
    h('option', { value: 'narrated' }, 'Narrated short'),
    h('option', { value: 'silent' }, 'Silent short (on-screen text)'),
  )
  const renderCheck = h('input', { id: 'production-render', type: 'checkbox', checked: true })
  const contextInput = h('textarea', {
    id: 'production-context',
    rows: 2,
    maxlength: 4000,
    placeholder: 'Audience, tone, facts to include…',
  })
  const formatHint = h('div', { class: 'production-hint', 'aria-live': 'polite' })
  const paintFormatHint = (): void => replace(formatHint, integrationHint(formatSelect.value, detail?.narration))
  formatSelect.addEventListener('change', paintFormatHint)
  paintFormatHint()
  const productionOptions = h(
    'div',
    { class: 'production-options', hidden: true },
    h('div', { class: 'field field-inline' }, h('label', { for: 'production-format' }, 'Format'), formatSelect),
    formatHint,
    h('label', { class: 'check' }, renderCheck, h('span', null, 'Render the video')),
    h(
      'details',
      { class: 'context-details' },
      h('summary', null, 'Add context'),
      h('label', { for: 'production-context', class: 'sr-only' }, 'Context'),
      contextInput,
    ),
  )
  const sendButton = h('button', { type: 'submit', class: 'button button-primary composer-send' }, icon('send', 16), h('span', null, 'Send'))
  const composerHint = h('p', { class: 'composer-hint', id: 'composer-hint' }, 'Enter to send · Shift+Enter for a new line')

  const modeButtons = (['chat', 'production'] as const).map((value) =>
    h(
      'button',
      {
        type: 'button',
        class: 'segment',
        'aria-pressed': String(value === mode),
        onclick: () => setMode(value),
      },
      value === 'chat' ? 'Chat with the orchestrator' : 'Full production',
    ),
  )

  const composer = h(
    'form',
    { class: 'composer', 'aria-label': 'Compose' },
    h('div', { class: 'composer-top' }, h('div', { class: 'segmented segmented-small', role: 'group', 'aria-label': 'Mode' }, modeButtons)),
    h('label', { for: 'composer-input', class: 'sr-only' }, 'Message'),
    input,
    productionOptions,
    h('div', { class: 'composer-foot' }, composerHint, sendButton),
  )
  input.setAttribute('aria-describedby', 'composer-hint')

  const personaRows = h('div', { class: 'persona-rows' })
  const scenesSection = h('div', { class: 'project-scenes' })
  const personalitySlot = h('div', { class: 'personality-switch' })
  const jobSection = h('div', { class: 'job-section' })
  const mediaSection = h('div', { class: 'project-media' })
  const narrationSection = h('div', { class: 'project-narration' })
  const narrationChip = h('button', { type: 'button', class: 'chip chip-button narration-chip', onclick: () => openTab('narration') })

  let tab: PanelTab = 'activity'
  const tabDefs: { id: PanelTab; label: string; glyph: string }[] = [
    { id: 'activity', label: 'Activity', glyph: 'activity' },
    { id: 'scenes', label: 'Scenes', glyph: 'scenes' },
    { id: 'narration', label: 'Narration', glyph: 'voice' },
    { id: 'exports', label: 'Exports', glyph: 'download' },
  ]
  const tabButtons = tabDefs.map((def) =>
    h(
      'button',
      {
        type: 'button',
        role: 'tab',
        id: `tab-${def.id}`,
        class: 'panel-tab',
        'aria-controls': `tabpanel-${def.id}`,
        onclick: () => openTab(def.id),
      },
      icon(def.glyph, 16),
      h('span', null, def.label),
    ),
  )
  const tabPanels: Record<PanelTab, HTMLElement> = {
    activity: h('div', { role: 'tabpanel', id: 'tabpanel-activity', 'aria-labelledby': 'tab-activity', class: 'panel-body' }, personaRows, jobSection),
    scenes: h('div', { role: 'tabpanel', id: 'tabpanel-scenes', 'aria-labelledby': 'tab-scenes', class: 'panel-body' }, scenesSection),
    narration: h('div', { role: 'tabpanel', id: 'tabpanel-narration', 'aria-labelledby': 'tab-narration', class: 'panel-body' }, narrationSection),
    exports: h('div', { role: 'tabpanel', id: 'tabpanel-exports', 'aria-labelledby': 'tab-exports', class: 'panel-body' }, mediaSection),
  }
  const tabList = h('div', { class: 'panel-tabs', role: 'tablist', 'aria-label': 'Project panel' }, tabButtons)
  tabList.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft' && event.key !== 'Home' && event.key !== 'End') return
    event.preventDefault()
    const at = tabDefs.findIndex((d) => d.id === tab)
    const nextIndex =
      event.key === 'Home' ? 0 : event.key === 'End' ? tabDefs.length - 1 : (at + (event.key === 'ArrowRight' ? 1 : -1) + tabDefs.length) % tabDefs.length
    openTab(tabDefs[nextIndex]!.id)
    tabButtons[nextIndex]!.focus()
  })

  function paintTabs(): void {
    tabDefs.forEach((def, i) => {
      const selected = def.id === tab
      tabButtons[i]!.setAttribute('aria-selected', String(selected))
      tabButtons[i]!.tabIndex = selected ? 0 : -1
      tabPanels[def.id].hidden = !selected
    })
  }

  function openTab(next: PanelTab): void {
    tab = next
    paintTabs()
    setPanel(true)
  }

  const panel = h(
    'aside',
    { class: 'activity', id: 'activity-panel', 'aria-label': 'Project panel' },
    h(
      'div',
      { class: 'activity-head' },
      tabList,
      h(
        'button',
        { type: 'button', class: 'icon-button panel-close', 'aria-label': 'Close panel', onclick: () => setPanel(false) },
        icon('close', 18),
      ),
    ),
    tabPanels.activity,
    tabPanels.scenes,
    tabPanels.narration,
    tabPanels.exports,
  )
  paintTabs()

  const conversation = h('section', { class: 'conversation', 'aria-label': 'Conversation' }, thread, notice, composer)

  const page = h(
    'div',
    { class: 'page-project' },
    h('header', { class: 'project-header' }, titleSlot, h('div', { class: 'project-actions' }, personalitySlot, narrationChip, panelToggle, deleteButton)),
    conversation,
    panel,
  )

  replace(outlet, h('div', { class: 'page page-loading' }, loadingState('Opening project…')))

  // --- Behaviour ---------------------------------------------------------------------

  function setPanel(open: boolean): void {
    page.classList.toggle('panel-open', open)
    panelToggle.setAttribute('aria-expanded', String(open))
  }

  function setMode(next: Mode): void {
    mode = next
    modeButtons.forEach((button, index) => button.setAttribute('aria-pressed', String((index === 0 ? 'chat' : 'production') === mode)))
    productionOptions.hidden = mode !== 'production'
    input.placeholder = mode === 'chat' ? 'Message the orchestrator…' : 'What should we produce? e.g. “A 40-second short on how bees make honey”'
    composerHint.textContent =
      mode === 'chat'
        ? 'Enter to send · Shift+Enter for a new line'
        : 'The orchestrator runs each stage through its specialists and reuses verified work. Rendering can take several minutes.'
    replace(sendButton, icon(mode === 'chat' ? 'send' : 'film', 16), h('span', null, mode === 'chat' ? 'Send' : 'Start production'))
    updateComposer()
    input.focus()
  }

  function busy(): boolean {
    return Boolean(job && !isTerminal(job.status))
  }

  function updateComposer(): void {
    const readiness = state.readiness
    const needed = mode === 'chat' ? ['planner'] : ['planner', 'production']
    const blocked = setupNotice(readiness, needed)
    replace(notice, blocked)
    const disabled = busy() || Boolean(blocked)
    sendButton.disabled = disabled
    input.readOnly = busy()
    if (busy()) {
      composerHint.textContent = `${speakerName()} is working. You can cancel from Activity.`
    } else if (mode === 'chat') {
      composerHint.textContent = 'Enter to send · Shift+Enter for a new line'
    }
  }

  function autoGrow(): void {
    input.style.height = 'auto'
    input.style.height = `${Math.min(input.scrollHeight, 240)}px`
  }

  input.addEventListener('input', autoGrow)
  input.addEventListener('keydown', (event) => {
    if (mode === 'chat' && event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault()
      composer.requestSubmit()
    }
  })

  composer.addEventListener('submit', (event) => {
    event.preventDefault()
    void submit()
  })

  async function submit(): Promise<void> {
    const text = input.value.trim()
    if (!text || busy() || !detail) return
    if (mode === 'production' && text.length < 5) {
      toast('Describe the video in a few more words.', 'error')
      return
    }
    sendButton.disabled = true
    try {
      if (mode === 'chat') {
        const response = await studio.sendMessage(projectId, text)
        detail.messages.push(response.message)
        upsertProject(response.project)
        detail.title = response.project.title
        startJob(response.job)
      } else {
        const options: ProductionOptions = {
          task: text,
          render_video: renderCheck.checked,
          short_format: formatSelect.value as ProductionOptions['short_format'],
        }
        const context = contextInput.value.trim()
        if (context) options.context = context
        const response = await studio.runProduction(projectId, options)
        detail.messages.push(response.message)
        startJob(response.job)
        void refreshProjects()
      }
      input.value = ''
      contextInput.value = ''
      autoGrow()
      renderTitle()
    } catch (error) {
      if (error instanceof ApiError && error.code === 'not_configured') {
        void refreshReadiness().then(updateComposer)
      }
      toast(errorMessage(error), 'error', 8000)
    } finally {
      updateComposer()
    }
  }

  function startJob(next: Job): void {
    watcher?.stop()
    job = next
    events = next.events ?? []
    renderAll()
    if (isTerminal(next.status)) {
      void onJobDone()
      return
    }
    watcher = watchJob(next.id, {
      after: events.length ? events[events.length - 1]!.seq : 0,
      onUpdate(update, newEvents) {
        job = update
        events = events.concat(newEvents)
        renderActivity()
        renderPending()
        updateComposer()
      },
      onDone() {
        void onJobDone()
      },
      onError(error) {
        toast(`Lost track of the job: ${error.message}`, 'error')
      },
    })
  }

  async function onJobDone(): Promise<void> {
    if (disposed) return
    if (job?.status === 'failed' && job.error) {
      const guidance = errorGuidance(job.error)
      toast(`${job.error.message}${guidance.hint ? ` ${guidance.hint}` : ''}`, 'error', 9000)
    }
    await reload(false)
    void refreshProjects()
  }

  async function reload(initial: boolean): Promise<void> {
    try {
      detail = await studio.project(projectId)
    } catch (error) {
      if (disposed) return
      if (error instanceof ApiError && error.status === 404) {
        replace(
          outlet,
          h(
            'div',
            { class: 'page' },
            errorState(new Error('This project does not exist or was deleted.')),
            h('p', { class: 'center' }, h('a', { class: 'button', href: '#/' }, 'Back to Studio')),
          ),
        )
        return
      }
      if (initial) {
        replace(outlet, h('div', { class: 'page' }, errorState(error, () => void reload(true))))
      } else {
        toast(errorMessage(error), 'error')
      }
      return
    }
    if (disposed) return
    upsertProject(detail)

    // Image checks report inside the scene search that started them.
    const pageJobs = detail.jobs.filter((j) => j.kind !== 'image_check')
    const active = pageJobs.find((j) => !isTerminal(j.status))
    const latest = active ?? pageJobs[0] ?? null
    if (initial) {
      replace(outlet, page)
      if (latest) {
        try {
          const full = await studio.job(latest.id, 0)
          if (disposed) return
          if (!isTerminal(full.status)) {
            startJob(full)
          } else {
            job = full
            events = full.events ?? []
          }
        } catch {
          job = latest
        }
      }
      renderAll()
      applyDraft()
      input.focus()
    } else {
      if (job && latest && latest.id === job.id) {
        job = { ...job, ...latest, events: undefined }
      }
      renderAll()
    }
  }

  function applyDraft(): void {
    const key = `framefusion:draft:${projectId}`
    const draft = sessionStorage.getItem(key)
    if (!draft) return
    sessionStorage.removeItem(key)
    input.value = draft
    autoGrow()
    if (!busy() && state.readiness?.planner.ready) {
      void submit()
    }
  }

  async function deleteProject(): Promise<void> {
    if (!detail) return
    const ok = await confirmDialog({
      title: 'Delete this project?',
      body: `“${detail.title}” and its conversation will be deleted. Generated files stay in your media library.`,
      confirm: 'Delete project',
      danger: true,
    })
    if (!ok) return
    try {
      await studio.deleteProject(projectId)
      removeProject(projectId)
      toast('Project deleted.', 'success')
      navigate('/')
    } catch (error) {
      toast(errorMessage(error), 'error')
    }
  }

  // --- Rendering -----------------------------------------------------------------------

  function renderAll(): void {
    renderTitle()
    renderPersonality()
    renderThread()
    renderActivity()
    renderScenes()
    renderMedia()
    renderNarrationChip()
    if (!narrationSection.firstChild) renderNarration()
    paintFormatHint()
    updateComposer()
  }

  // --- Narration ------------------------------------------------------------------------

  function renderNarrationChip(): void {
    const voice = effectiveNarration(detail?.narration)
    if (!voice) {
      narrationChip.hidden = true
      return
    }
    narrationChip.hidden = false
    narrationChip.classList.toggle('chip-warn', !voice.ready)
    narrationChip.classList.toggle('chip-override', voice.overridden)
    const label = `${PROVIDER_NAME[voice.provider]}${voice.voiceLabel ? ` · ${voice.voiceLabel}` : ''}`
    narrationChip.setAttribute('aria-label', `Narration: ${label}${voice.overridden ? ', project override' : ''}. Open narration settings for this project.`)
    replace(narrationChip, icon(voice.ready ? 'voice' : 'alert', 14), h('span', { class: 'chip-text' }, label), voice.overridden ? h('span', { class: 'chip-tag' }, 'Override') : null)
  }

  function renderNarration(): void {
    if (!detail) return
    const current = detail
    const base = state.app?.narration
    const override = current.narration
    const providerSelect = h(
      'select',
      { id: 'project-narration-provider' },
      h('option', { value: '' }, base ? `Use the default (${narrationSummary(base.provider, base.voice_label, base.voice)})` : 'Use the default'),
      h('option', { value: 'edge', selected: override.provider === 'edge' }, 'Free — Edge TTS'),
      h('option', { value: 'elevenlabs', selected: override.provider === 'elevenlabs' }, 'ElevenLabs'),
    )
    const voiceInput = h('input', {
      id: 'project-narration-voice',
      list: 'project-edge-voices',
      value: override.provider === 'edge' ? override.voice : '',
      placeholder: base?.provider === 'edge' ? `Default voice: ${base.voice_label || base.voice}` : 'e.g. en-GB-SoniaNeural',
      maxlength: 80,
      autocomplete: 'off',
      spellcheck: 'false',
      'aria-describedby': 'project-narration-voice-hint',
    })
    const voiceOptions = h('datalist', { id: 'project-edge-voices' })
    const voiceHint = h('p', { class: 'field-hint', id: 'project-narration-voice-hint' }, 'Type to search voices by name or language. Leave empty to use the default Edge voice.')
    const voiceField = h('div', { class: 'field' }, h('label', { for: 'project-narration-voice' }, 'Edge voice'), voiceInput, voiceOptions, voiceHint)
    const elevenNote = h('p', { class: 'field-hint' }, 'Uses the ElevenLabs voice and model saved in Settings → Narration, and your ElevenLabs credits.')
    const status = h('div', { class: 'readiness-line', role: 'status', 'aria-live': 'polite' })
    const save = h('button', { type: 'submit', class: 'button button-primary button-small' }, 'Save for this project')
    const clear = h('button', { type: 'button', class: 'button button-small button-ghost', hidden: !override.provider }, icon('retry', 14), 'Use the default')
    let voices: EdgeVoice[] = []

    function resolveVoice(): { id: string; label: string } {
      const typed = voiceInput.value.trim()
      if (!typed) return { id: '', label: '' }
      const match = voices.find((v) => v.id.toLowerCase() === typed.toLowerCase() || v.name.toLowerCase() === typed.toLowerCase())
      return match ? { id: match.id, label: match.name } : { id: typed, label: '' }
    }

    function paintStatus(): void {
      const chosen = providerSelect.value as NarrationProvider | ''
      voiceField.hidden = chosen !== 'edge'
      elevenNote.hidden = chosen !== 'elevenlabs'
      const voice = effectiveNarration(current.narration)
      if (!voice) return
      const differs =
        voice.overridden && base ? voice.provider !== base.provider || (Boolean(current.narration.voice) && current.narration.voice !== base.voice) : false
      status.className = `readiness-line ${voice.ready ? 'ok' : 'warn'}`
      replace(
        status,
        icon(voice.ready ? 'checkCircle' : 'alert', 16),
        h(
          'span',
          null,
          voice.ready
            ? `${voice.overridden ? 'This project narrates with' : 'Follows the default:'} ${narrationSummary(voice.provider, voice.voiceLabel, voice.voice)}.`
            : (voice.problem ?? 'Narration is not ready.'),
          differs ? h('span', { class: 'tag tag-warn' }, 'Differs from default') : null,
        ),
      )
    }

    async function persist(value: { provider: NarrationProvider; voice: string; voice_label: string } | null): Promise<void> {
      save.disabled = clear.disabled = true
      try {
        const updated = await narration.setProjectOverride(current.id, value)
        current.narration = updated.narration
        upsertProject(updated)
        toast(value ? 'Narration saved for this project.' : 'This project now follows the default narration.', 'success')
        renderNarration()
        renderNarrationChip()
        paintFormatHint()
      } catch (error) {
        toast(errorMessage(error), 'error')
        save.disabled = clear.disabled = false
      }
    }

    providerSelect.addEventListener('change', paintStatus)
    clear.addEventListener('click', () => void persist(null))
    const form = h(
      'form',
      { class: 'project-narration-form' },
      h('p', { class: 'field-hint' }, 'Narrated shorts in this project use this voice. Change the default for all projects in ', h('a', { class: 'link', href: '#/settings/narration' }, 'Settings → Narration'), '.'),
      h('div', { class: 'field' }, h('label', { for: 'project-narration-provider' }, 'Provider'), providerSelect),
      voiceField,
      elevenNote,
      status,
      h('div', { class: 'form-actions form-actions-start' }, save, clear),
    )
    form.addEventListener('submit', (event) => {
      event.preventDefault()
      const chosen = providerSelect.value as NarrationProvider | ''
      if (!chosen) {
        void persist(null)
        return
      }
      const voice = chosen === 'edge' ? resolveVoice() : { id: '', label: '' }
      if (chosen === 'edge' && voice.id && voices.length && !voices.some((v) => v.id === voice.id)) {
        voiceInput.setAttribute('aria-invalid', 'true')
        voiceHint.className = 'field-warn'
        voiceHint.textContent = 'That voice is not in the Edge voice list. Pick one from the suggestions.'
        return
      }
      voiceInput.removeAttribute('aria-invalid')
      void persist({ provider: chosen, voice: voice.id, voice_label: voice.label })
    })

    replace(narrationSection, form)
    paintStatus()
    void loadEdgeVoices()
      .then((list) => {
        voices = list
        replace(voiceOptions, list.map((v) => h('option', { value: v.id }, `${v.name} — ${edgeVoiceMeta(v)}`)))
        const known = list.find((v) => v.id === voiceInput.value)
        if (known) voiceInput.title = known.name
      })
      .catch(() => {
        voiceHint.textContent = 'The Edge voice list needs internet. You can still type a voice ID such as en-GB-SoniaNeural.'
      })
  }

  async function retryNarration(failed: Job, provider?: NarrationProvider): Promise<void> {
    try {
      const next = await narration.retry(failed.id, provider)
      toast(`Recording the narration again${provider ? ` with ${PROVIDER_NAME[provider]}` : ''}. The script and visuals are reused.`, 'success')
      startJob(next)
    } catch (error) {
      toast(errorMessage(error), 'error', 8000)
      if (error instanceof ApiError && error.code === 'not_configured') void refreshApp().then(renderAll).catch(() => {})
    }
  }

  function narrationActions(failed: Job): Node[] {
    if (!failed.error?.can_retry_narration || failed.status !== 'failed') return []
    const used = (failed.error.provider as NarrationProvider | undefined) ?? effectiveNarration(detail?.narration)?.provider
    const actions: Node[] = [
      h('button', { type: 'button', class: 'button button-primary button-small', onclick: () => void retryNarration(failed) }, icon('voice', 14), 'Retry narration'),
    ]
    if (used === 'elevenlabs') {
      actions.push(h('button', { type: 'button', class: 'button button-small', onclick: () => void retryNarration(failed, 'edge') }, icon('globe', 14), 'Retry with free Edge TTS'))
    } else if (used === 'edge' && state.integrations?.elevenlabs.configured) {
      actions.push(h('button', { type: 'button', class: 'button button-small', onclick: () => void retryNarration(failed, 'elevenlabs') }, icon('key', 14), 'Retry with ElevenLabs'))
    }
    return actions
  }

  function renderTitle(): void {
    if (!detail) return
    const current = detail
    const heading = h('h1', { tabindex: '-1', 'data-autofocus': true }, current.title)
    const edit = h(
      'button',
      { type: 'button', class: 'icon-button', 'aria-label': 'Rename project', title: 'Rename', onclick: startRename },
      icon('edit', 16),
    )
    replace(titleSlot, heading, edit)
    document.title = `${current.title} · FrameFusion`

    function startRename(): void {
      const field = h('input', { class: 'title-input', value: current.title, maxlength: 120, 'aria-label': 'Project title' })
      const save = async (): Promise<void> => {
        const value = field.value.trim()
        if (!value || value === current.title) {
          renderTitle()
          return
        }
        try {
          const updated = await studio.renameProject(projectId, value)
          current.title = updated.title
          upsertProject(updated)
        } catch (error) {
          toast(errorMessage(error), 'error')
        }
        renderTitle()
      }
      field.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          event.preventDefault()
          void save()
        } else if (event.key === 'Escape') {
          renderTitle()
          edit.focus()
        }
      })
      field.addEventListener('blur', () => void save(), { once: true })
      replace(titleSlot, field)
      field.focus()
      field.select()
    }
  }

  function renderThread(): void {
    if (!detail) return
    const nearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 120
    const jobsById = new Map(detail.jobs.map((j) => [j.id, j]))
    if (job) jobsById.set(job.id, job)

    const items: Node[] = []
    if (!detail.messages.length) {
      items.push(introCard())
    }
    const shown = new Set<string>()
    for (const message of detail.messages) {
      items.push(messageView(message))
      if (message.role === 'user' && message.job_id) {
        const related = jobsById.get(message.job_id)
        if (related && (related.status === 'failed' || related.status === 'cancelled')) {
          items.push(failureCard(related, related.id === job?.id))
          shown.add(related.id)
        }
      }
    }
    if (job && job.kind === 'narration' && (job.status === 'failed' || job.status === 'cancelled') && !shown.has(job.id)) {
      items.push(failureCard(job, true))
    }
    items.push(h('div', { class: 'pending-slot' }))
    replace(thread, items)
    renderPending()
    if (nearBottom || busy()) thread.scrollTop = thread.scrollHeight
  }

  function introCard(): HTMLElement {
    const look = personality(detail?.effective_personality)
    return h(
      'div',
      { class: `intro tone-${look.tone}` },
      h('div', { class: 'intro-avatars' }, avatar(look.id, { size: 'lg', portrait: true })),
      h('h2', null, 'What are we making?'),
      h(
        'p',
        null,
        `Chat with the orchestrator (${look.name}) to shape the idea, research facts and draft a script. When you are ready, switch to Full production: it hands the script, scene images, narration and render to its specialists, checks each result and shows you what it used.`,
      ),
    )
  }

  function messageView(message: ChatMessage): HTMLElement {
    if (message.role === 'user') {
      return h(
        'article',
        { class: 'message message-user' },
        h('div', { class: 'bubble' }, h('p', { class: 'plain' }, message.content)),
        h('time', { class: 'message-time', datetime: message.created_at }, relativeTime(message.created_at)),
      )
    }
    const look = personality(message.persona ?? detail?.effective_personality)
    const body = h('div', { class: 'markdown' })
    body.innerHTML = renderMarkdown(message.content)
    return h(
      'article',
      { class: `message message-assistant message-${look.tone}` },
      avatar(look.id, { size: 'sm' }),
      h(
        'div',
        { class: 'message-main' },
        h(
          'header',
          { class: 'message-head' },
          h('strong', null, look.name),
          h('span', { class: 'role-tag' }, 'Orchestrator'),
          h('time', { class: 'message-time', datetime: message.created_at }, relativeTime(message.created_at)),
        ),
        body,
        message.attachments.length
          ? h('div', { class: 'attachments' }, message.attachments.map((a) => attachmentView(a)))
          : null,
      ),
    )
  }

  function failureCard(failed: Job, latest: boolean): HTMLElement {
    const guidance = errorGuidance(failed.error)
    const cancelled = failed.status === 'cancelled'
    const narrationFailed = failed.error?.kind === 'narration_failed'
    const narrationButtons = latest ? narrationActions(failed) : []
    const fullRetry = failed.kind !== 'narration' && guidance.retry
    return h(
      'div',
      { class: `failure ${cancelled ? 'failure-cancelled' : ''}${narrationFailed ? ' failure-narration' : ''}`, role: cancelled ? 'status' : 'alert' },
      icon(cancelled ? 'stop' : narrationFailed ? 'voice' : 'alert', 18),
      h(
        'div',
        { class: 'failure-body' },
        h('strong', null, cancelled ? 'Run cancelled' : narrationFailed ? 'Narration could not be recorded' : 'This request failed'),
        failed.error && !cancelled ? h('p', null, failed.error.message) : null,
        guidance.hint && !cancelled ? h('p', { class: 'muted' }, guidance.hint) : null,
        failed.kind === 'production' && !narrationFailed
          ? h('p', { class: 'muted' }, `${failed.error?.stage ? `Stopped at ${stageLabel(failed.error.stage)}. ` : ''}Resuming reuses every verified stage and redoes only what is missing.`)
          : null,
        latest
          ? h(
              'div',
              { class: 'failure-actions' },
              narrationButtons,
              fullRetry
                ? h(
                    'button',
                    { type: 'button', class: `button button-small${narrationButtons.length ? ' button-ghost' : ''}`, onclick: () => void retry(failed) },
                    icon('retry', 14),
                    narrationButtons.length ? 'Rerun everything' : failed.kind === 'production' ? 'Resume production' : 'Retry',
                  )
                : null,
              guidance.settings && !cancelled
                ? h('a', { class: 'button button-small button-ghost', href: settingsHref(failed.error) }, icon('settings', 14), narrationFailed ? 'Narration settings' : 'Open Settings')
                : null,
            )
          : null,
      ),
    )
  }

  async function retry(failed: Job): Promise<void> {
    try {
      const next = await studio.retryJob(failed.id)
      if (detail) {
        for (const message of detail.messages) {
          if (message.job_id === failed.id) message.job_id = next.id
        }
      }
      startJob(next)
    } catch (error) {
      toast(errorMessage(error), 'error', 8000)
      if (error instanceof ApiError && error.code === 'not_configured') void refreshReadiness().then(updateComposer)
    }
  }

  /** The personality snapshotted for the running job; a switch mid-run applies next turn. */
  function jobPersonality(): PersonalityId {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const persona = events[i]!.persona
      if (persona) return persona
    }
    const snapshot = job?.input.personality
    if (typeof snapshot === 'string' && snapshot in PERSONALITIES) return snapshot as PersonalityId
    return detail?.effective_personality ?? 'director'
  }

  /** The specialist or service doing the latest step, or null when the orchestrator is. */
  function activeSpecialist(): string | null {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const event = events[i]!
      if (!event.agent || event.type === 'status') continue
      return event.agent === 'orchestrator' ? null : event.agent
    }
    return null
  }

  function speakerName(): string {
    return personality(jobPersonality()).name
  }

  function stageLabel(stage: Stage): string {
    return STAGES.find((s) => s.id === stage)?.label ?? stage
  }

  function latestMessage(): string {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const event = events[i]!
      if (event.message && event.type !== 'status') return event.message
    }
    return job?.status === 'queued' ? 'Waiting to start…' : 'Getting started…'
  }

  function renderPending(): void {
    const slot = thread.querySelector('.pending-slot')
    if (!slot) return
    if (!job || isTerminal(job.status)) {
      replace(slot)
      return
    }
    const look = personality(jobPersonality())
    const specialist = activeSpecialist()
    replace(
      slot,
      h(
        'div',
        { class: `message message-assistant message-${look.tone} message-pending` },
        avatar(look.id, { size: 'sm', state: 'working' }),
        h(
          'div',
          { class: 'message-main' },
          h(
            'header',
            { class: 'message-head' },
            h('strong', null, look.name),
            h('span', { class: 'role-tag' }, job.cancel_requested ? 'Cancelling…' : specialist ? `Delegated to ${specialistName(specialist)}` : STATUS_LABEL[job.status]),
          ),
          h('p', { class: 'pending-line' }, h('span', { class: 'typing', 'aria-hidden': 'true' }, h('i'), h('i'), h('i')), h('span', null, latestMessage())),
          job.kind === 'production' ? stepProgress(true) : null,
        ),
      ),
    )
    thread.scrollTop = thread.scrollHeight
  }

  /**
   * Stage status: the persisted tasks, overlaid with step events from a production that is
   * still running (the task list is refreshed when the job ends).
   */
  function stepStates(): Map<Stage, { status: StepState; task: ProductionTask | null }> {
    const states = new Map<Stage, { status: StepState; task: ProductionTask | null }>()
    for (const step of STAGES) states.set(step.id, { status: 'pending', task: null })
    for (const task of detail?.production.tasks ?? []) states.set(task.stage, { status: task.status, task })
    if (job && job.kind === 'production' && !isTerminal(job.status)) {
      for (const event of events) {
        if (event.type !== 'step') continue
        const stage = event.data.stage as Stage | undefined
        const status = EVENT_STEP[String(event.data.status ?? '')]
        const entry = stage ? states.get(stage) : undefined
        if (entry && status) entry.status = status
      }
    }
    return states
  }

  function stepProgress(compact: boolean): HTMLElement {
    const states = stepStates()
    const done = [...states.values()].filter((s) => s.status === 'verified' || s.status === 'skipped').length
    const canRedo = !busy() && Boolean(detail?.production.tasks.some((t) => t.stage === 'brief' && t.status === 'verified'))
    return h(
      'div',
      { class: `steps ${compact ? 'steps-compact' : ''}` },
      h(
        'div',
        { class: 'steps-bar', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': STAGES.length, 'aria-valuenow': done, 'aria-label': 'Production progress' },
        h('span', { style: `width:${(done / STAGES.length) * 100}%` }),
      ),
      compact
        ? h('p', { class: 'muted' }, `${done} of ${STAGES.length} stages verified or skipped`)
        : h(
            'ol',
            { class: 'step-list' },
            STAGES.map((step) => {
              const { status, task } = states.get(step.id)!
              const visual = STEP_VISUAL[status]
              const redo =
                canRedo && step.id !== 'brief' && status !== 'skipped' && status !== 'pending'
                  ? h(
                      'button',
                      {
                        type: 'button',
                        class: 'icon-button icon-button-small',
                        'aria-label': `Redo ${step.label} and everything after it`,
                        title: `Redo from ${step.label}`,
                        onclick: () => void rerunFrom(step.id),
                      },
                      icon('retry', 14),
                    )
                  : null
              const notes = [...(task?.limitations ?? []), ...(task?.error && status === 'failed' ? [task.error.message] : [])]
              return [
                h(
                  'li',
                  { class: `step step-${visual} step-${status}${step.owner === 'Orchestrator' ? ' step-orchestrator' : ''}` },
                  h('span', { class: 'step-marker', 'aria-hidden': 'true' }, visual === 'done' ? icon('check', 12) : visual === 'failed' ? icon('close', 12) : null),
                  h('span', { class: 'step-glyph', 'aria-hidden': 'true' }, icon(step.glyph, 14)),
                  h(
                    'span',
                    { class: 'step-label' },
                    step.label,
                    h('span', { class: 'step-owner' }, ` · ${step.owner}`),
                    task && task.attempt > 1 ? h('span', { class: 'step-owner' }, ` · attempt ${task.attempt} of ${task.max_attempts}`) : null,
                  ),
                  h('span', { class: 'step-status' }, STEP_LABEL[status]),
                  redo,
                ),
                notes.length ? h('ul', { class: 'step-limits' }, notes.slice(0, 3).map((note) => h('li', null, note))) : null,
              ]
            }).flat(),
          ),
    )
  }

  async function rerunFrom(stage: Stage): Promise<void> {
    const ok = await confirmDialog({
      title: `Redo from ${stageLabel(stage)}?`,
      body: 'Earlier verified stages are reused. This stage and everything after it run again, which may call your AI model and narration provider.',
      confirm: 'Redo',
    })
    if (!ok) return
    try {
      const response = await studio.rerun(projectId, stage)
      detail?.messages.push(response.message)
      startJob(response.job)
    } catch (error) {
      toast(errorMessage(error), 'error', 8000)
    }
  }

  function orchestratorState(): AvatarState {
    const needed: Route[] = job?.kind === 'production' ? ROUTES : ['planner']
    if (needed.some((route) => state.readiness && !state.readiness[route].ready)) return 'setup'
    if (!job) return 'idle'
    if (!isTerminal(job.status)) return activeSpecialist() ? 'idle' : 'working'
    if (job.status === 'failed') return 'error'
    if (job.status === 'succeeded') return 'success'
    return 'idle'
  }

  /** Tool calls in the current run: running ones first, then the most recent results. */
  function toolActivity(): HTMLElement | null {
    const calls = new Map<string, { tool: string; agent: string | null; label: string; status: 'running' | 'ok' | 'failed'; error: string }>()
    let n = 0
    for (const event of events) {
      if (event.type !== 'tool') continue
      const tool = String(event.data.tool ?? 'tool')
      if (event.data.status === 'running') {
        calls.set(`${tool}:${n++}`, { tool, agent: event.agent, label: event.message, status: 'running', error: '' })
      } else {
        const open = [...calls.entries()].reverse().find(([, call]) => call.tool === tool && call.status === 'running')
        const result = { status: event.data.ok === false ? ('failed' as const) : ('ok' as const), error: String(event.data.error ?? '') }
        if (open) Object.assign(open[1], result)
        else calls.set(`${tool}:${n++}`, { tool, agent: event.agent, label: event.message, ...result })
      }
    }
    if (!calls.size) return null
    const list = [...calls.values()].slice(-12)
    return h(
      'details',
      { class: 'tool-activity', open: Boolean(job && !isTerminal(job.status)) },
      h('summary', null, `Tool calls (${calls.size})`),
      h(
        'ul',
        { class: 'tool-list' },
        list.map((call) =>
          h(
            'li',
            { class: `tool-call tool-${call.status}` },
            call.status === 'running' ? spinner('Running') : icon(call.status === 'ok' ? 'check' : 'error', 14),
            h(
              'span',
              { class: 'tool-text' },
              h('code', null, call.tool),
              h('span', { class: 'muted' }, ` · ${call.agent ? (call.agent === 'orchestrator' ? 'Orchestrator' : specialistName(call.agent)) : 'Tool'}`),
              call.error ? h('span', { class: 'tool-error' }, call.error) : null,
            ),
          ),
        ),
      ),
    )
  }

  function renderActivity(): void {
    const look = personality(job && !isTerminal(job.status) ? jobPersonality() : detail?.effective_personality)
    const orchestrator = orchestratorState()
    const status: Record<AvatarState, string> = {
      working: 'Working now',
      setup: 'Needs setup',
      error: 'Hit a problem',
      success: 'Finished',
      idle: job && !isTerminal(job.status) ? 'Supervising' : 'Idle',
    }
    const planner = state.readiness?.planner
    const specialist = job && !isTerminal(job.status) ? activeSpecialist() : null
    replace(
      personaRows,
      h(
        'div',
        { class: `persona-row tone-${look.tone}` },
        avatar(look.id, { size: 'md', state: orchestrator }),
        h(
          'div',
          { class: 'persona-text' },
          h('strong', null, look.name, h('span', { class: 'role-tag' }, 'Orchestrator')),
          h('span', { class: `persona-status status-${orchestrator}` }, status[orchestrator]),
          planner?.ready
            ? h('code', { class: 'persona-model', title: `${planner.provider_label} · ${planner.model}` }, planner.model ?? '')
            : planner
              ? h('a', { class: 'link', href: '#/settings' }, 'Set up provider')
              : null,
        ),
      ),
      specialist
        ? h(
            'div',
            { class: 'persona-row specialist-row' },
            h('span', { class: 'route-icon', 'aria-hidden': 'true' }, icon('workflow', 18)),
            h(
              'div',
              { class: 'persona-text' },
              h('strong', null, specialistName(specialist), h('span', { class: 'role-tag' }, 'Reports to the orchestrator')),
              h('span', { class: 'persona-status status-working' }, 'Working now'),
            ),
          )
        : null,
    )

    if (!job) {
      replace(
        jobSection,
        detail?.production.tasks.length
          ? h('div', { class: 'job-card' }, h('h3', null, 'Production stages'), stepProgress(false))
          : h('p', { class: 'muted activity-empty' }, 'No runs yet. The orchestrator’s progress, its specialists’ tasks and every tool call show up here while they work.'),
      )
      return
    }

    const current = job
    const active = !isTerminal(current.status)
    const elapsed = elapsedText(current)
    const actions: Node[] = []
    if (active) {
      actions.push(
        h(
          'button',
          {
            type: 'button',
            class: 'button button-small',
            disabled: current.cancel_requested,
            onclick: async () => {
              try {
                job = await studio.cancelJob(current.id)
                renderActivity()
                renderPending()
              } catch (error) {
                toast(errorMessage(error), 'error')
              }
            },
          },
          icon('stop', 14),
          current.cancel_requested ? 'Cancelling…' : 'Cancel',
        ),
      )
    } else if (current.status === 'failed' || current.status === 'cancelled') {
      const narrationButtons = narrationActions(current)
      if (narrationButtons.length) actions.push(narrationButtons[0]!)
      else if (current.kind !== 'narration') actions.push(h('button', { type: 'button', class: 'button button-small', onclick: () => void retry(current) }, icon('retry', 14), 'Retry'))
    }

    replace(
      jobSection,
      h(
        'div',
        { class: 'job-card' },
        h(
          'div',
          { class: 'job-head' },
          h(
            'div',
            null,
            h('h3', null, JOB_TITLE[current.kind] ?? 'Run'),
            h(
              'p',
              { class: `job-status status-${current.status}` },
              active ? spinner('Working') : null,
              h('span', null, STATUS_LABEL[current.status] ?? current.status),
              elapsed ? h('span', { class: 'muted', 'data-elapsed': true }, ` · ${elapsed}`) : null,
            ),
          ),
          actions.length ? h('div', { class: 'job-actions' }, actions) : null,
        ),
        current.kind === 'production' ? stepProgress(false) : null,
        current.error && current.status === 'failed' ? h('p', { class: 'job-error' }, current.error.message) : null,
        toolActivity(),
        events.length
          ? h(
              'details',
              { class: 'timeline-details', open: active },
              h('summary', null, `Event log (${events.length})`),
              h(
                'ol',
                { class: 'timeline' },
                events
                  .filter((e) => e.message)
                  .slice(-60)
                  .map((event) =>
                    h(
                      'li',
                      { class: `event event-${event.type}${event.data.ok === false ? ' event-failed' : ''}` },
                      event.persona ? avatar(event.persona, { size: 'xs' }) : h('span', { class: 'event-dot', 'aria-hidden': 'true' }),
                      h('span', { class: 'event-text' }, event.message),
                    ),
                  ),
              ),
            )
          : null,
        current.usage.length
          ? h(
              'div',
              { class: 'usage' },
              h('h4', null, 'Model usage'),
              h(
                'ul',
                null,
                current.usage.map((entry) =>
                  h(
                    'li',
                    null,
                    h('code', null, entry.model),
                    h(
                      'span',
                      { class: 'muted' },
                      `${entry.calls} call${entry.calls === 1 ? '' : 's'} · ${entry.input_tokens.toLocaleString()} in / ${entry.output_tokens.toLocaleString()} out tokens`,
                    ),
                  ),
                ),
              ),
            )
          : null,
      ),
    )
  }

  // --- Personality --------------------------------------------------------------------------

  function renderPersonality(): void {
    if (!detail) return
    const current = detail
    const fallback = personality(state.app?.personality)
    const look = personality(current.effective_personality)
    const select = h(
      'select',
      { id: 'project-personality', class: 'personality-select' },
      h('option', { value: '', selected: !current.personality }, `Default (${fallback.name})`),
      PERSONALITY_IDS.map((id) => h('option', { value: id, selected: current.personality === id }, PERSONALITIES[id].name)),
    )
    select.addEventListener('change', async () => {
      const value = (select.value || null) as PersonalityId | null
      select.disabled = true
      try {
        const updated = await studio.setPersonality(projectId, value)
        current.personality = updated.personality
        current.effective_personality = updated.effective_personality
        upsertProject(updated)
        const name = personality(updated.effective_personality).name
        toast(
          updated.personality_applies === 'next_turn'
            ? `${name} takes over after the current run finishes.`
            : `${name} will reply from now on. Same specialists and tools.`,
          'success',
        )
      } catch (error) {
        toast(errorMessage(error), 'error')
      }
      renderPersonality()
      renderThread()
      renderActivity()
    })
    replace(
      personalitySlot,
      avatar(look.id, { size: 'xs' }),
      h('label', { for: 'project-personality', class: 'sr-only' }, 'Orchestrator personality for this project'),
      select,
    )
    personalitySlot.className = `personality-switch tone-${look.tone}`
    personalitySlot.title = 'Personality changes the voice only; capabilities are identical'
  }

  // --- Scenes and images -----------------------------------------------------------------

  function assetById(id: string | null): MediaAsset | null {
    if (!id || !detail) return null
    return detail.media.find((asset) => asset.id === id) ?? null
  }

  function sourceLine(asset: MediaAsset): HTMLElement | null {
    const source = asset.source
    if (!source) return null
    const link = (href: string | null, text: string): Node =>
      href ? h('a', { class: 'link', href, target: '_blank', rel: 'noopener noreferrer' }, text) : document.createTextNode(text)
    const parts: Node[] = []
    if (source.provider) parts.push(document.createTextNode(source.provider.charAt(0).toUpperCase() + source.provider.slice(1)))
    if (source.creator) parts.push(link(source.creator_url, source.creator))
    parts.push(link(source.license_url, source.license || 'Licence not stated'))
    if (source.source_page_url) parts.push(link(source.source_page_url, 'Source page'))
    return h(
      'div',
      { class: 'scene-source' },
      h(
        'p',
        null,
        parts.flatMap((part, i) => (i ? [document.createTextNode(' · '), part] : [part])),
        ' ',
        h('span', { class: `tag ${source.rights_status === 'documented' ? 'tag-ok' : 'tag-warn'}` }, source.user_supplied && source.rights_status === 'unknown' ? 'Your link, rights unknown' : RIGHTS_LABEL[source.rights_status]),
      ),
      source.attribution ? h('p', { class: 'muted scene-attribution' }, source.attribution) : null,
    )
  }

  const sceneCards = new Map<number, HTMLElement>()
  const scenesHead = h('div', { class: 'scenes-summary' })

  function sceneStatus(scene: SceneState, hasImage: boolean): SceneVisualStatus | null {
    if (scene.visual?.status) return scene.visual.status
    if (hasImage) return 'selected'
    return scene.gap ? 'no_suitable_result' : null
  }

  function paintScenesHead(): void {
    if (!detail) return
    const scenes = detail.production.scenes
    const withImages = scenes.filter((scene) => assetById(scene.asset_id)).length
    const review = scenes.filter((scene) => sceneStatus(scene, Boolean(assetById(scene.asset_id))) === 'awaiting_review').length
    const render = detail.production.tasks.find((task) => task.stage === 'render')
    const stale = render && (render.status === 'invalidated' || render.status === 'proposed')
    const counts = [`${scenes.length} scenes`, `${withImages} with images`]
    if (withImages < scenes.length) counts.push(`${scenes.length - withImages} without`)
    if (review) counts.push(`${review} awaiting review`)
    replace(
      scenesHead,
      h(
        'div',
        { class: 'scenes-head' },
        h('p', { class: 'muted' }, counts.join(' · ')),
        h(
          'button',
          {
            type: 'button',
            class: `button button-small${stale ? ' button-primary' : ''}`,
            disabled: busy(),
            onclick: () => void rerunFrom('render'),
          },
          icon('film', 14),
          'Re-render video',
        ),
      ),
      stale ? h('p', { class: 'field-warn' }, icon('alert', 14), 'Scene images changed since the last render. Re-render to update the video.') : null,
    )
  }

  function renderScenes(): void {
    if (!detail) return
    const scenes = detail.production.scenes
    sceneCards.clear()
    if (!scenes.length) {
      replace(
        scenesSection,
        h(
          'div',
          { class: 'panel-empty' },
          icon('scenes', 20),
          h('p', null, 'Scenes appear here once the script specialist has written the script. The visual specialist then writes a brief per scene and looks for an image that genuinely matches it, or tells you honestly that it found none.'),
        ),
      )
      return
    }
    paintScenesHead()
    const cards = scenes.map((scene) => {
      const card = sceneCard(scene)
      sceneCards.set(scene.index, card)
      return card
    })
    replace(scenesSection, scenesHead, h('ol', { class: 'scene-list' }, cards))
  }

  /** Apply a new production state but repaint only the scene that changed. */
  function applySceneChange(production: ProductionState, sceneIndex: number): void {
    if (!detail) return
    detail.production = production
    const scene = production.scenes.find((item) => item.index === sceneIndex)
    const current = sceneCards.get(sceneIndex)
    if (!scene || !current?.isConnected) {
      renderScenes()
    } else {
      const next = sceneCard(scene)
      current.replaceWith(next)
      sceneCards.set(sceneIndex, next)
      paintScenesHead()
    }
    renderActivity()
  }

  function rememberAsset(asset: MediaAsset): void {
    if (detail && !detail.media.some((item) => item.id === asset.id)) detail.media.unshift(asset)
  }

  function briefView(scene: SceneState, visual: SceneVisualState): HTMLElement | null {
    const brief = visual.brief
    if (!brief) return scene.visual_description ? h('p', { class: 'muted' }, `Visual: ${scene.visual_description}`) : null
    const row = (term: string, value: string): HTMLElement => h('div', null, h('dt', null, term), h('dd', null, value))
    const names = brief.named_entities.map((entity) => entity.name).join(', ')
    return h(
      'details',
      { class: 'scene-brief' },
      h('summary', null, `Must show: ${brief.subject}`),
      h(
        'dl',
        { class: 'brief-list' },
        brief.action ? row('Action', brief.action) : null,
        names ? row('Named subject', names) : null,
        row('Accuracy', SPECIFICITY_LABEL[brief.specificity]),
        row('Kind', brief.visual_type),
        brief.composition ? row('Framing', brief.composition) : null,
        brief.acceptable_alternatives.length ? row('Also fine', brief.acceptable_alternatives.join('; ')) : null,
        brief.excluded.length ? row('Avoid', brief.excluded.join(', ')) : null,
      ),
      visual.searches.length
        ? h(
            'ul',
            { class: 'brief-searches' },
            visual.searches.map((search) =>
              h(
                'li',
                null,
                `“${search.query}” on ${SOURCE_NAME[search.source] ?? search.source}: `,
                search.error ? search.error : `${search.count ?? 0} result${search.count === 1 ? '' : 's'}`,
              ),
            ),
          )
        : null,
      brief.derived ? h('p', { class: 'field-hint' }, 'This brief was derived from the script because the model’s brief was unusable.') : null,
    )
  }

  function assessmentTags(assessment: ImageAssessment | null, verification: ImageVerification | null): HTMLElement | null {
    const checked = verification ?? assessment?.verification ?? null
    if (!assessment && !checked) return null
    return h(
      'div',
      { class: 'tag-row' },
      assessment ? h('span', { class: `tag ${assessment.decision === 'accept' ? 'tag-ok' : assessment.decision === 'reject' ? 'tag-danger' : 'tag-warn'}` }, DECISION_LABEL[assessment.decision]) : null,
      checked ? h('span', { class: `tag ${checked === 'metadata' || checked === 'none' ? 'tag-warn' : ''}` }, VERIFICATION_LABEL[checked]) : null,
      assessment
        ? h('span', { class: 'tag', title: 'Orders the candidates. A heuristic, not a probability.' }, `Fit ${assessment.score}/100`)
        : null,
    )
  }

  function sceneCard(scene: SceneState): HTMLElement {
    const asset = assetById(scene.asset_id)
    const visual = scene.visual
    const status = sceneStatus(scene, Boolean(asset))
    const searchSlot = h('div', { class: 'scene-search', hidden: true })
    const disabled = busy() || status === 'searching'
    const chosenBy = { visual: 'Chosen by the visual specialist', auto: 'Picked automatically', user: 'Chosen by you' } as const

    const openSearch = (source: ImageSearchSource = 'auto'): void => {
      searchSlot.hidden = false
      replace(searchSlot, imageSearch(scene, source))
      searchSlot.querySelector<HTMLInputElement>('input')?.focus()
    }
    const button = (label: string, glyph: string, onclick: () => void, extra = ''): HTMLButtonElement =>
      h('button', { type: 'button', class: `button button-small${extra}`, disabled, onclick }, icon(glyph, 14), label)

    const fileInput = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', hidden: true, 'aria-label': `Upload an image for scene ${scene.index + 1}` })
    fileInput.addEventListener('change', async () => {
      const file = fileInput.files?.[0]
      fileInput.value = ''
      if (!file) return
      try {
        const saved = await studio.uploadImage(projectId, file, scene.index)
        rememberAsset(saved.asset)
        if (saved.production) applySceneChange(saved.production, scene.index)
        renderMedia()
        toast('Image uploaded and marked “rights unknown” until you confirm you may use it. Re-render to update the video.', 'success', 7000)
      } catch (error) {
        toast(errorMessage(error), 'error', 8000)
      }
    })

    const actions: (HTMLElement | null)[] = [
      button(asset ? 'Search again' : 'Find an image', asset ? 'refresh' : 'search', () => openSearch()),
      button('Google Images', 'globe', () => openSearch('link')),
      button('Upload', 'upload', () => fileInput.click()),
      !asset && status !== 'title_card'
        ? button('Use a title card', 'captions', async () => {
            try {
              applySceneChange(await studio.useTitleCard(projectId, scene.index), scene.index)
              toast('Scene set to a title card. Re-render to update the video.', 'success')
            } catch (error) {
              toast(errorMessage(error), 'error')
            }
          })
        : null,
      asset
        ? button(
            'Remove',
            'trash',
            async () => {
              const ok = await confirmDialog({
                title: `Remove the image from scene ${scene.index + 1}?`,
                body: 'The scene renders with a plain title card until you pick another image. The file stays in your media library.',
                confirm: 'Remove image',
                danger: true,
              })
              if (!ok) return
              try {
                applySceneChange(await studio.setSceneImage(projectId, scene.index, null), scene.index)
                toast('Image removed. Re-render to update the video.', 'success')
              } catch (error) {
                toast(errorMessage(error), 'error')
              }
            },
            ' button-danger',
          )
        : null,
    ]

    const statusInfo = status ? SCENE_STATUS[status] : null
    const unresolvedText = status === 'title_card' ? 'You chose a title card for this scene.' : visual?.note || scene.gap || (status === 'searching' ? 'The visual specialist is looking.' : 'No image yet.')
    const alternatives = visual?.alternatives ?? []
    return h(
      'li',
      { class: `scene-card${!asset && status !== 'title_card' && status !== 'searching' ? ' scene-gap' : ''}` },
      h(
        'div',
        { class: 'scene-media' },
        asset
          ? h('img', { src: asset.url, alt: `Scene ${scene.index + 1}: ${asset.source?.title ?? asset.display_name}`, loading: 'lazy', decoding: 'async' })
          : h('div', { class: 'scene-placeholder', 'aria-hidden': 'true' }, icon(status === 'title_card' ? 'captions' : 'image', 22)),
      ),
      h(
        'div',
        { class: 'scene-body' },
        h(
          'div',
          { class: 'scene-title' },
          h('h4', null, `Scene ${scene.index + 1}`),
          statusInfo
            ? h('span', { class: `tag ${statusInfo.tone}`, role: 'status' }, status === 'searching' ? spinner('Searching') : null, statusInfo.label)
            : null,
        ),
        scene.narration || scene.on_screen_text ? h('p', { class: 'scene-text' }, scene.narration || scene.on_screen_text) : null,
        visual ? briefView(scene, visual) : null,
        asset ? sourceLine(asset) : null,
        asset ? assessmentTags(visual?.assessment ?? null, visual?.verification ?? null) : null,
        asset && visual?.illustrative ? h('p', { class: 'field-hint' }, icon('info', 12), ' Used as an illustration, not the exact subject.') : null,
        asset && visual?.assessment?.visible_content ? h('p', { class: 'muted' }, `Seen in the image: ${visual.assessment.visible_content}`) : null,
        asset && scene.selected_by ? h('p', { class: 'muted scene-why' }, chosenBy[scene.selected_by], scene.reason ? ` · ${scene.reason}` : '') : null,
        asset && visual?.rights_status === 'unknown' && scene.selected_by !== 'user'
          ? h('p', { class: 'field-warn' }, icon('alert', 14), 'Reuse rights are unknown. It stays out of the video until you choose it yourself.')
          : null,
        !asset ? h('p', { class: status === 'title_card' ? 'muted' : 'field-warn' }, status === 'title_card' ? null : icon('alert', 14), unresolvedText) : null,
        !asset && visual?.missing ? h('p', { class: 'muted' }, `A suitable image would show: ${visual.missing}`) : null,
        h('div', { class: 'scene-actions' }, actions, fileInput),
      ),
      alternatives.length
        ? h(
            'details',
            { class: 'scene-alternatives', open: !asset },
            h('summary', null, `${alternatives.length} other candidate${alternatives.length === 1 ? '' : 's'} checked against the brief`),
            h('ul', { class: 'candidate-grid' }, alternatives.map((alternative) => candidateCard(alternative, scene))),
          )
        : null,
      searchSlot,
    )
  }

  function imageSearch(scene: SceneState, initialSource: ImageSearchSource = 'auto'): HTMLElement {
    const startQuery = scene.visual?.brief?.queries[0]?.query ?? scene.image_query
    const query = h('input', { type: 'text', value: startQuery, maxlength: 4000, 'aria-label': 'Search terms or link', autocomplete: 'off' })
    const keyed = (service: 'pexels' | 'pixabay' | 'brave'): boolean => Boolean(state.integrations?.[service]?.configured)
    const option = (value: ImageSearchSource, label: string, ready = true): HTMLOptionElement =>
      h('option', { value, disabled: !ready, selected: value === initialSource }, ready ? label : `${label} (not set up)`)
    const source = h(
      'select',
      { 'aria-label': 'Source' },
      option('auto', 'Best licensed sources'),
      option('wikimedia', 'Wikimedia Commons (named places, people, diagrams)'),
      option('pexels', 'Pexels', keyed('pexels')),
      option('pixabay', 'Pixabay', keyed('pixabay')),
      option('openverse', 'Openverse (Creative Commons)'),
      option('brave', 'Brave web search (rights unknown)', keyed('brave')),
      option('link', 'Link from Google Images or any page'),
      option('url', 'Image URL'),
      option('webpage', 'Images on a webpage'),
    )
    const orientation = h(
      'select',
      { 'aria-label': 'Orientation' },
      h('option', { value: 'portrait' }, 'Portrait'),
      h('option', { value: 'landscape' }, 'Landscape'),
      h('option', { value: 'square' }, 'Square'),
      h('option', { value: 'any' }, 'Any'),
    )
    const submit = h('button', { type: 'submit', class: 'button button-small button-primary' }, icon('search', 14), 'Search')
    const results = h('div', { class: 'candidate-results', 'aria-live': 'polite' })
    // Opens in your own browser; FrameFusion never requests Google itself.
    const googleTerms = startQuery || scene.visual?.brief?.subject || scene.visual_description || ''
    const googleHelp = h(
      'div',
      { class: 'google-assist', hidden: true },
      h(
        'a',
        {
          class: 'button button-small',
          href: `${GOOGLE_IMAGES_SEARCH}${encodeURIComponent(googleTerms)}`,
          target: '_blank',
          rel: 'noopener noreferrer',
        },
        icon('external', 14),
        googleTerms ? `Search Google Images for “${googleTerms}”` : 'Open Google Images',
      ),
      h(
        'p',
        { class: 'field-hint' },
        'Open a result, copy its address (or right-click the large image and copy the image address) and paste it here. FrameFusion looks for the original on the publisher’s page, checks it against the brief and downloads it safely. Google previews and results pages can’t be used, and rights stay unknown until you approve them.',
      ),
    )
    const syncPlaceholder = (): void => {
      const isLink = source.value === 'url' || source.value === 'webpage' || source.value === 'link'
      query.placeholder = source.value === 'link' ? 'Paste the Google result, page or image link' : isLink ? 'https://…' : 'e.g. honeybee on a flower'
      if (isLink && query.value === startQuery) query.value = ''
      orientation.hidden = source.value === 'link'
      googleHelp.hidden = source.value !== 'link'
    }
    source.addEventListener('change', syncPlaceholder)
    const form = h(
      'form',
      { class: 'image-search-form' },
      googleHelp,
      h('div', { class: 'image-search-row' }, query, source, orientation, submit),
      h(
        'p',
        { class: 'field-hint' },
        'Licences come from the source; check them before publishing. Brave web search uses paid API credits and finds images whose rights are unknown, as do your own links.',
      ),
      results,
    )

    const showResults = (found: ImageSearchResult): void => {
      let candidates = found.candidates
      const grid = h('ul', { class: 'candidate-grid' })
      const paint = (): void => replace(grid, candidates.map((candidate) => candidateCard(candidate, scene)))
      const checkable = candidates.filter((candidate) => candidate.assessment?.decision !== 'reject').slice(0, 6)
      const checkNote = h('div', { 'aria-live': 'polite' })
      const visionReady = Boolean(state.readiness?.production.ready)
      const check = h(
        'button',
        {
          type: 'button',
          class: 'button button-small',
          disabled: !visionReady,
          title: visionReady ? 'Uses one paid call to the Production model.' : 'Set up the Production model in Settings to check images visually.',
        },
        icon('eye', 14),
        `Check ${checkable.length === 1 ? 'it' : `${checkable.length} images`} with vision`,
      )
      check.addEventListener('click', async () => {
        check.disabled = true
        replace(checkNote, h('p', { class: 'muted' }, spinner('Checking'), ' The visual specialist is looking at the images…'))
        let started: Job
        try {
          started = await studio.checkImages(projectId, scene.index, checkable.map((candidate) => candidate.candidate_id))
        } catch (error) {
          replace(checkNote, h('p', { class: 'form-error', role: 'alert' }, errorMessage(error)))
          check.disabled = false
          return
        }
        const finish = (done: Job): void => {
          if (done.status !== 'succeeded') {
            replace(checkNote, h('p', { class: 'form-error', role: 'alert' }, done.error?.message ?? 'The image check didn’t finish.'))
            check.disabled = false
            return
          }
          const result = done.result as unknown as ImageCheckResult
          const byId = new Map(result.assessments.map((assessment) => [assessment.candidate_id, assessment]))
          candidates = candidates
            .map((candidate) => ({ ...candidate, assessment: byId.get(candidate.candidate_id) ?? candidate.assessment }))
            .sort((a, b) => (b.assessment?.score ?? 0) - (a.assessment?.score ?? 0))
          paint()
          replace(
            checkNote,
            result.limitations.length ? h('ul', { class: 'step-limits' }, result.limitations.map((note) => h('li', null, note))) : null,
            h('p', { class: 'muted' }, result.vision_available ? 'Checked against the brief by looking at each image.' : 'The images couldn’t be inspected visually; the metadata check still applies.'),
          )
        }
        if (isTerminal(started.status)) {
          finish(started)
        } else {
          const watch: JobWatcher = watchJob(started.id, {
            onUpdate: () => {
              if (disposed || !form.isConnected) watch.stop()
            },
            onDone: finish,
            onError: (error) => {
              replace(checkNote, h('p', { class: 'form-error', role: 'alert' }, errorMessage(error)))
              check.disabled = false
            },
          })
        }
      })
      paint()
      replace(
        results,
        found.limitations.length ? h('ul', { class: 'step-limits' }, found.limitations.map((note) => h('li', null, note))) : null,
        candidates.length
          ? [checkable.length && candidates.some((candidate) => candidate.assessment) ? h('div', { class: 'scene-actions' }, check) : null, checkNote, grid]
          : h('p', { class: 'muted' }, found.source === 'link' ? 'No suitable image found on that link. Try another result.' : 'No usable images found. Try other words or another source.'),
      )
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault()
      const text = query.value.trim()
      if (!text) return
      submit.disabled = true
      replace(results, loadingState(source.value === 'link' ? 'Finding the original image…' : 'Searching…'))
      try {
        showResults(
          await studio.searchImages(projectId, {
            query: text,
            source: source.value as ImageSearchSource,
            orientation: orientation.value as 'portrait' | 'landscape' | 'square' | 'any',
            scene_index: scene.index,
          }),
        )
      } catch (error) {
        replace(results, h('p', { class: 'form-error', role: 'alert' }, errorMessage(error)))
      }
      submit.disabled = false
    })
    syncPlaceholder()
    return form
  }

  function candidateCard(candidate: SearchedImage, scene: SceneState): HTMLElement {
    const assessment = candidate.assessment ?? null
    const illustrative = assessment?.decision === 'illustrative'
    const label = illustrative
      ? 'Use as a labelled illustration'
      : candidate.rights_status === 'unknown'
        ? `Approve rights and use for scene ${scene.index + 1}`
        : `Use for scene ${scene.index + 1}`
    const use = h('button', { type: 'button', class: 'button button-small' }, icon('download', 14), label)
    use.addEventListener('click', async () => {
      use.disabled = true
      replace(use, spinner('Downloading'), ' Downloading…')
      try {
        const saved = await studio.downloadImage(projectId, candidate.candidate_id, scene.index, illustrative)
        rememberAsset(saved.asset)
        toast(`${saved.reused_existing_file ? 'Already downloaded; reused the file.' : 'Image saved.'} Re-render to update the video.`, 'success')
        if (saved.production) applySceneChange(saved.production, scene.index)
        renderMedia()
      } catch (error) {
        toast(errorMessage(error), 'error', 8000)
        use.disabled = false
        replace(use, icon('download', 14), label)
      }
    })
    const size = candidate.width && candidate.height ? `${candidate.width}×${candidate.height}` : null
    return h(
      'li',
      { class: 'candidate' },
      candidate.preview_url
        ? h('img', { src: candidate.preview_url, alt: candidate.title, loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' })
        : h('div', { class: 'scene-placeholder', 'aria-hidden': 'true' }, icon('image', 20)),
      h(
        'div',
        { class: 'candidate-body' },
        h('strong', null, candidate.title || 'Untitled'),
        h(
          'p',
          { class: 'muted' },
          [candidate.publisher ?? SOURCE_NAME[candidate.provider] ?? candidate.provider, candidate.creator, size].filter(Boolean).join(' · '),
        ),
        candidate.discovered_via === 'google_images' || candidate.found_on_page !== undefined
          ? h(
              'div',
              { class: 'tag-row' },
              candidate.discovered_via === 'google_images' ? h('span', { class: 'tag' }, 'Found by you via Google Images') : null,
              candidate.found_on_page === true ? h('span', { class: 'tag tag-ok' }, 'Original on the publisher’s page') : null,
              candidate.found_on_page === false ? h('span', { class: 'tag tag-warn' }, 'Not seen on the publisher’s page') : null,
            )
          : null,
        assessment ? assessmentTags(assessment, null) : null,
        assessment?.visible_content ? h('p', null, `Seen: ${assessment.visible_content}`) : null,
        assessment?.reasons.length ? h('ul', { class: 'candidate-reasons' }, assessment.reasons.slice(0, 3).map((reason) => h('li', null, reason))) : null,
        h(
          'p',
          null,
          candidate.license_url ? h('a', { class: 'link', href: candidate.license_url, target: '_blank', rel: 'noopener noreferrer' }, candidate.license) : candidate.license,
          ' ',
          h('span', { class: `tag ${candidate.rights_status === 'documented' ? 'tag-ok' : 'tag-warn'}` }, RIGHTS_LABEL[candidate.rights_status]),
        ),
        candidate.usage_note ? h('p', { class: 'field-hint' }, candidate.usage_note) : null,
        candidate.source_page_url
          ? h('a', { class: 'link', href: candidate.source_page_url, target: '_blank', rel: 'noopener noreferrer' }, candidate.publisher ? 'Publisher’s page' : 'View source', icon('external', 12))
          : null,
        use,
      ),
    )
  }

  function renderMedia(): void {
    if (!detail) return
    if (!detail.media.length) {
      replace(
        mediaSection,
        h(
          'div',
          { class: 'panel-empty' },
          icon('film', 20),
          h('p', null, 'Final cuts, narration and music land here after a production renders. Nothing is exported until you run one.'),
        ),
      )
      return
    }
    const groups: { kind: MediaAsset['kind']; label: string; glyph: string }[] = [
      { kind: 'video', label: 'Final cuts', glyph: 'video' },
      { kind: 'audio', label: 'Narration and audio', glyph: 'sound' },
      { kind: 'image', label: 'Images', glyph: 'image' },
    ]
    replace(
      mediaSection,
      groups.map((group) => {
        const assets = detail!.media.filter((asset) => asset.kind === group.kind)
        if (!assets.length) return null
        return h(
          'section',
          { class: `export-group export-${group.kind}` },
          h('h3', { class: 'activity-label' }, icon(group.glyph, 14), `${group.label} (${assets.length})`),
          h('ul', { class: 'project-media-list' }, assets.map((asset) => h('li', null, mediaThumb(asset)))),
        )
      }),
      h('a', { class: 'link', href: '#/media' }, 'Open the media library', icon('chevron', 14)),
    )
  }

  function elapsedText(current: Job): string {
    const start = current.started_at ?? current.created_at
    const end = current.finished_at ? new Date(current.finished_at).getTime() : Date.now()
    const seconds = Math.max(0, Math.round((end - new Date(start).getTime()) / 1000))
    if (seconds < 60) return `${seconds}s`
    return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`
  }

  tick = window.setInterval(() => {
    if (!job || isTerminal(job.status)) return
    const label = jobSection.querySelector('[data-elapsed]')
    if (label) label.textContent = ` · ${elapsedText(job)}`
  }, 1000)

  void reload(true)
  if (!state.readiness) void refreshReadiness().then(updateComposer).catch(() => {})

  return () => {
    disposed = true
    watcher?.stop()
    window.clearInterval(tick)
    document.title = 'FrameFusion'
  }
}
