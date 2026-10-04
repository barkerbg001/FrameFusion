// First-run setup wizard. Progress is stored on the server so it resumes after a reload,
// and every step reuses the Settings components. Nothing here starts a paid generation.
import {
  app,
  providers,
  studio,
  type AISettings,
  type OnboardingStep,
  ROUTES,
  type ProviderState,
} from '../api.ts'
import { avatar, personality } from '../avatars.ts'
import { h, icon, replace, spinner } from '../dom.ts'
import welcomeArt from '../assets/illustrations/welcome.webp'
import { brandLockup } from '../shell.ts'
import { refreshApp, setAppState, state, upsertProject } from '../state.ts'
import { currentTheme } from '../theme.ts'
import { toast } from '../toast.ts'
import { errorMessage, errorState, loadingState } from './common.ts'
import {
  AI_PROVIDERS,
  credentialCard,
  invalidateModels,
  modelsForm,
  narrationPanel,
  narrationSummary,
  personalityPicker,
  pexelsPanel,
  themePicker,
} from './integrations.ts'

const STEP_LABELS: Record<OnboardingStep, string> = {
  welcome: 'Welcome',
  providers: 'AI provider',
  models: 'Models',
  narration: 'Narration',
  media: 'Stock media',
  appearance: 'Appearance',
  review: 'Review',
}

const OPTIONAL: ReadonlySet<OnboardingStep> = new Set(['narration', 'media', 'appearance'])

const optional = (node: HTMLElement | null): HTMLElement[] => (node ? [node] : [])

export function renderOnboarding(root: HTMLElement, exit: (path: string) => void): () => void {
  let steps: OnboardingStep[] = ['welcome', 'providers', 'models', 'narration', 'media', 'appearance', 'review']
  let current: OnboardingStep = 'welcome'
  let furthest = 0
  let providerStates: ProviderState[] = []
  let encryptionConfigured = true
  let ai: AISettings | null = null
  let disposed = false
  let busy = false

  const indicator = h('ol', { class: 'wizard-steps', 'aria-label': 'Setup progress' })
  const body = h('div', { class: 'wizard-body' })
  const error = h('p', { class: 'form-error wizard-error', role: 'alert', hidden: true })
  const backButton = h('button', { type: 'button', class: 'button button-ghost' }, 'Back')
  const skipButton = h('button', { type: 'button', class: 'button button-ghost' }, 'Skip for now')
  const nextButton = h('button', { type: 'button', class: 'button button-primary' }, 'Continue')
  const exitLink = h('a', { class: 'link wizard-exit', href: '#/settings', hidden: true }, 'Exit setup')
  const footer = h('div', { class: 'wizard-footer' }, backButton, h('div', { class: 'wizard-footer-end' }, skipButton, nextButton))

  const page = h(
    'div',
    { class: 'wizard' },
    h('header', { class: 'wizard-top' }, h('span', { class: 'brand' }, brandLockup()), exitLink),
    h('div', { class: 'wizard-frame' }, indicator, h('main', { class: 'wizard-card', id: 'main' }, body, error, footer)),
  )
  replace(root, page)

  const index = (step: OnboardingStep): number => steps.indexOf(step)

  function paintIndicator(): void {
    const at = index(current)
    replace(
      indicator,
      steps.map((step, i) => {
        const done = i < at || (state.app?.onboarding.skipped.includes(step) ?? false)
        const reachable = i <= furthest || Boolean(state.app?.onboarding.completed)
        const skipped = state.app?.onboarding.skipped.includes(step) ?? false
        const marker = h('span', { class: 'wizard-step-marker', 'aria-hidden': 'true' }, i < at && !skipped ? icon('check', 14) : String(i + 1))
        const label = h('span', { class: 'wizard-step-label' }, STEP_LABELS[step], skipped ? h('span', { class: 'wizard-step-note' }, 'Skipped') : null)
        const content =
          reachable && step !== current
            ? h('button', { type: 'button', class: 'wizard-step-button', onclick: () => void go(step) }, marker, label)
            : h('span', { class: 'wizard-step-button' }, marker, label)
        return h(
          'li',
          { class: `wizard-step${step === current ? ' current' : ''}${done ? ' done' : ''}`, 'aria-current': step === current ? 'step' : null },
          content,
        )
      }),
    )
  }

  function showError(message: string | null): void {
    error.hidden = !message
    error.textContent = message ?? ''
  }

  function setBusy(next: boolean, label?: string): void {
    busy = next
    for (const button of [backButton, skipButton, nextButton]) button.disabled = next
    if (next && label) replace(nextButton, spinner(label), ` ${label}…`)
  }

  async function persist(update: { step?: OnboardingStep; skip?: OnboardingStep; complete?: boolean }): Promise<void> {
    const onboarding = await app.onboarding(update)
    if (state.app) state.app.onboarding = onboarding
  }

  async function go(step: OnboardingStep, skip?: OnboardingStep): Promise<void> {
    if (busy) return
    showError(null)
    setBusy(true, 'Saving')
    try {
      await persist({ step, skip })
      current = step
      furthest = Math.max(furthest, index(step))
      await renderStep()
    } catch (err) {
      showError(errorMessage(err))
    }
    setBusy(false)
    paintFooter()
  }

  function paintFooter(): void {
    const at = index(current)
    backButton.hidden = at === 0
    skipButton.hidden = !OPTIONAL.has(current)
    nextButton.hidden = current === 'review'
    replace(nextButton, current === 'welcome' ? 'Get started' : 'Continue', icon('chevron', 16))
    exitLink.hidden = !state.app?.onboarding.completed
    paintIndicator()
  }

  async function loadCredentials(): Promise<void> {
    const list = await providers.list()
    providerStates = list.providers
    encryptionConfigured = list.encryption_configured
  }

  function heading(title: string, description: string): HTMLElement {
    return h(
      'header',
      { class: 'wizard-heading' },
      h('p', { class: 'wizard-kicker' }, `Step ${index(current) + 1} of ${steps.length}${OPTIONAL.has(current) ? ' · Optional' : ''}`),
      h('h1', { tabindex: '-1', id: 'wizard-title' }, title),
      h('p', { class: 'page-description' }, description),
    )
  }

  function encryptionBanner(): HTMLElement | null {
    if (encryptionConfigured) return null
    return h(
      'div',
      { class: 'notice notice-error', role: 'alert' },
      icon('alert', 20),
      h(
        'div',
        { class: 'notice-body' },
        h('strong', null, 'Key storage is not configured'),
        h('p', null, 'Set FRAMEFUSION_ENCRYPTION_KEY in api/.env (run `npm run setup`) and restart the API before saving keys.'),
      ),
    )
  }

  function readinessList(): HTMLElement {
    const readiness = state.readiness
    return h(
      'ul',
      { class: 'readiness-list' },
      ROUTES.map((route) => {
        const info = readiness?.[route]
        const ready = Boolean(info?.ready)
        return h(
          'li',
          { class: `readiness-item readiness-${route}` },
          avatar(state.app?.personality, { size: 'sm', state: ready ? 'success' : 'setup' }),
          h(
            'div',
            null,
            h('strong', null, info?.name ?? route),
            h('p', { class: ready ? 'muted' : 'field-warn' }, ready ? `${info?.provider_label} · ${info?.model}` : (info?.problem ?? 'Not set up yet.')),
          ),
        )
      }),
    )
  }

  // --- Steps ---------------------------------------------------------------------------

  async function renderStep(): Promise<void> {
    replace(body, loadingState('Loading…'))
    let content: Node[] = []
    switch (current) {
      case 'welcome':
        content = welcomeStep()
        break
      case 'providers':
        await loadCredentials()
        content = providersStep()
        break
      case 'models':
        await loadCredentials()
        ai = await providers.aiSettings()
        content = modelsStep()
        break
      case 'narration':
        content = narrationStep()
        break
      case 'media':
        await loadCredentials()
        content = mediaStep()
        break
      case 'appearance':
        content = appearanceStep()
        break
      case 'review':
        await loadCredentials()
        await refreshApp()
        content = reviewStep()
        break
    }
    if (disposed) return
    replace(body, content)
    paintFooter()
    body.querySelector<HTMLElement>('#wizard-title')?.focus({ preventScroll: true })
    window.scrollTo(0, 0)
  }

  function welcomeStep(): Node[] {
    return [
      h(
        'header',
        { class: 'wizard-heading wizard-hero' },
        h('img', { class: 'illustration wizard-illustration', src: welcomeArt, alt: '', width: 1200, height: 675, decoding: 'async' }),
        h('h1', { tabindex: '-1', id: 'wizard-title' }, 'Welcome to FrameFusion'),
        h('p', { class: 'page-description' }, 'One orchestrator plans your short with you, hands work to its specialists (script, visuals, narration, render) and checks the result. Pick how it talks to you, then connect what it needs. It takes a few minutes.'),
      ),
      personalityPicker(),
      h(
        'ul',
        { class: 'wizard-points' },
        h('li', null, icon('key', 16), h('span', null, 'You need an API key from at least one AI provider: OpenRouter, Google Gemini or Anthropic Claude.')),
        h('li', null, icon('voice', 16), h('span', null, 'Narration works without a key through free Edge TTS, an online Microsoft speech service. ElevenLabs (premium voices, music) and Pexels (stock footage) are optional.')),
        h('li', null, icon('check', 16), h('span', null, 'Keys are encrypted on this computer’s server and never sent back to the browser. Nothing is generated and no credits are used until you ask.')),
      ),
    ]
  }

  function providersStep(): Node[] {
    const cards = AI_PROVIDERS.map((name) => providerStates.find((p) => p.provider === name))
      .filter((p): p is ProviderState => Boolean(p))
      .map((p) =>
        credentialCard(p, {
          encryptionConfigured,
          onChange: async (next) => {
            providerStates = providerStates.map((item) => (item.provider === next.provider ? next : item))
            invalidateModels(next.provider)
            showError(null)
          },
        }),
      )
    return [
      heading('Connect an AI provider', 'Add a key for at least one provider. OpenRouter gives access to many model families with one key; Gemini and Claude connect directly. You can add the others later.'),
      ...optional(encryptionBanner()),
      h('div', { class: 'provider-list' }, cards),
    ]
  }

  function modelsStep(): Node[] {
    const summary = h('div', { class: 'wizard-summary' }, readinessList())
    const form = ai
      ? modelsForm({
          ai,
          providerStates,
          submitLabel: 'Save models',
          onSaved: (saved) => {
            ai = saved
            replace(summary, readinessList())
            showError(null)
          },
        })
      : errorState(new Error('Model settings did not load.'), () => void renderStep())
    return [
      heading('Choose models', 'Pick a default provider and model for the orchestrator. Optionally give the visual specialist its own model. Save, then continue.'),
      summary,
      form,
    ]
  }

  function narrationStep(): Node[] {
    return [
      heading(
        'Choose a narration voice',
        'Narrated shorts work out of the box with free Edge TTS: no key, but it needs internet and sends the narration text to Microsoft. Pick a voice, preview it if you like, and save. Switch to ElevenLabs any time.',
      ),
      narrationPanel({ submitLabel: 'Save narration' }),
    ]
  }

  function mediaStep(): Node[] {
    const provider = providerStates.find((p) => p.provider === 'pexels')
    if (!provider) return [heading('Stock media', 'Pexels is unavailable in this build.')]
    const panel = h('div', { class: 'media-panel' })
    let configured = provider.configured
    replace(panel, pexelsPanel(configured))
    return [
      heading('Stock footage from Pexels', 'Optional. Skip this step and add it any time in Settings → Stock media.'),
      ...optional(encryptionBanner()),
      h(
        'section',
        { class: 'media-block media-block-pexels' },
        h('p', { class: 'field-hint' }, h('strong', null, 'Unlocks: '), 'stock photo and video search and footage-based b-roll.', h('br'), h('strong', null, 'Without it: '), 'renders use text and generated visuals instead of stock footage.'),
        credentialCard(provider, {
          encryptionConfigured,
          onChange: async (next) => {
            providerStates = providerStates.map((item) => (item.provider === next.provider ? next : item))
            if (next.configured !== configured) {
              configured = next.configured
              replace(panel, pexelsPanel(configured))
            }
          },
        }),
        panel,
      ),
    ]
  }

  function appearanceStep(): Node[] {
    return [heading('Pick a look', 'Choose a theme. You can change it any time in Settings.'), themePicker()]
  }

  function reviewStep(): Node[] {
    const configuredAI = providerStates.filter((p) => p.kind === 'ai' && p.configured).map((p) => p.label)
    const readiness = state.readiness
    const integrations = state.integrations
    const skipped = state.app?.onboarding.skipped ?? []
    const theme = state.app?.theme ?? currentTheme()

    const row = (label: string, value: Node | string, ok: boolean, step: OnboardingStep): HTMLElement =>
      h(
        'li',
        { class: `review-row ${ok ? 'ok' : 'warn'}` },
        h('span', { class: 'review-icon', 'aria-hidden': 'true' }, icon(ok ? 'check' : 'alert', 16)),
        h('div', { class: 'review-text' }, h('strong', null, label), h('span', null, value)),
        h('button', { type: 'button', class: 'button button-small button-ghost', onclick: () => void go(step), 'aria-label': `Edit ${label}` }, 'Edit'),
      )

    const narrationRow = (): HTMLElement => {
      const info = state.app?.narration
      return row(
        'Narration',
        info ? (info.ready ? narrationSummary(info.provider, info.voice_label, info.voice) : (info.problem ?? 'Not ready')) : 'Not loaded',
        Boolean(info?.ready),
        'narration',
      )
    }

    const mediaRow = (name: 'elevenlabs' | 'pexels'): HTMLElement => {
      const info = integrations?.[name]
      const configured = Boolean(info?.configured)
      return row(
        info?.label ?? name,
        configured
          ? `Connected · ${info?.features}`
          : `${skipped.includes('media') ? 'Skipped' : 'Not set up'}. Needed for: ${info?.features ?? ''}. Add it later in Settings.`,
        configured,
        'media',
      )
    }

    const createButton = h('button', { type: 'button', class: 'button button-primary button-large' }, icon('plus', 16), 'Create your first project')
    const workspaceButton = h('button', { type: 'button', class: 'button' }, 'Go to the workspace')
    const finishError = h('p', { class: 'form-error', role: 'alert', hidden: true })
    const allReady = ROUTES.every((route) => Boolean(readiness?.[route].ready))

    async function finish(create: boolean): Promise<void> {
      createButton.disabled = workspaceButton.disabled = true
      finishError.hidden = true
      const target = create ? createButton : workspaceButton
      const original = Array.from(target.childNodes)
      replace(target, spinner('Finishing'), ' Finishing…')
      try {
        await persist({ step: 'review', complete: true })
        if (state.app) setAppState({ ...state.app })
        if (create) {
          const project = await studio.createProject()
          upsertProject(project)
          toast('Setup complete. Describe your first video to the orchestrator.', 'success')
          exit(`/projects/${project.id}`)
        } else {
          toast('Setup complete.', 'success')
          exit('/')
        }
      } catch (err) {
        finishError.textContent = errorMessage(err)
        finishError.hidden = false
        replace(target, ...original)
        createButton.disabled = workspaceButton.disabled = false
      }
    }
    createButton.addEventListener('click', () => void finish(true))
    workspaceButton.addEventListener('click', () => void finish(false))

    return [
      heading('Review and start', 'Here is what’s set up. Creating a project only opens an empty workspace; the orchestrator replies when you send a message.'),
      h(
        'ul',
        { class: 'review-list' },
        row('AI providers', configuredAI.length ? configuredAI.join(', ') : 'None connected', configuredAI.length > 0, 'providers'),
        row('Personality', personality(state.app?.personality).name, true, 'welcome'),
        ROUTES.map((route) => {
          const info = readiness?.[route]
          return row(info?.name ?? route, info?.ready ? `${info.provider_label} · ${info.model}` : (info?.problem ?? 'Not set up'), Boolean(info?.ready), 'models')
        }),
        narrationRow(),
        mediaRow('pexels'),
        row('Theme', theme.charAt(0).toUpperCase() + theme.slice(1), true, 'appearance'),
      ),
      allReady
        ? null
        : h('p', { class: 'field-warn' }, icon('alert', 14), 'The orchestrator needs a working AI provider and model before it can run. You can finish now and complete this in Settings.'),
      finishError,
      h('div', { class: 'wizard-finish' }, createButton, workspaceButton),
    ].filter((node): node is HTMLElement => node !== null)
  }

  // --- Navigation ----------------------------------------------------------------------

  function validate(): string | null {
    if (current === 'providers' && !providerStates.some((p) => p.kind === 'ai' && p.configured)) {
      return 'Save a key for at least one AI provider to continue.'
    }
    if (current === 'models') {
      const blocked = ROUTES
        .map((p) => state.readiness?.[p])
        .filter((r) => !r?.ready)
      if (blocked.length) return blocked.map((r) => r?.problem ?? 'Save your model choices first.').join(' ')
    }
    return null
  }

  nextButton.addEventListener('click', async () => {
    if (current === 'models') await refreshApp().catch(() => {})
    const problem = validate()
    if (problem) {
      showError(problem)
      return
    }
    const next = steps[index(current) + 1]
    if (next) void go(next)
  })
  backButton.addEventListener('click', () => {
    const previous = steps[index(current) - 1]
    if (previous) void go(previous)
  })
  skipButton.addEventListener('click', () => {
    const next = steps[index(current) + 1]
    if (next) void go(next, current)
  })

  async function start(): Promise<void> {
    replace(body, loadingState('Loading setup…'))
    try {
      const appState = await refreshApp()
      steps = appState.onboarding.steps
      current = steps.includes(appState.onboarding.step) ? appState.onboarding.step : 'welcome'
      furthest = appState.onboarding.completed ? steps.length - 1 : index(current)
      await renderStep()
    } catch (err) {
      replace(body, errorState(err, () => void start()))
      footer.hidden = true
      return
    }
    footer.hidden = false
  }

  void start()
  return () => {
    disposed = true
  }
}
