import { app, providers, studio, type AISettings, type ProviderState } from '../api.ts'
import { h, icon, prefersReducedMotion, replace, spinner } from '../dom.ts'
import { navigate } from '../router.ts'
import { refreshApp, refreshProjects, state } from '../state.ts'
import { toast } from '../toast.ts'
import { confirmDialog, errorMessage, errorState, focusHeading, loadingState, pageHeader } from './common.ts'
import {
  AI_PROVIDERS,
  credentialCard,
  importChoicesPanel,
  invalidateModels,
  modelsForm,
  narrationPanel,
  personalityPicker,
  pexelsPanel,
  themePicker,
} from './integrations.ts'

const LEGACY_KEY = 'framefusion:chats'

export function settingsView(outlet: HTMLElement, params: Record<string, string> = {}): () => void {
  let providerStates: ProviderState[] = []
  let encryptionConfigured = true
  let ai: AISettings | null = null
  let disposed = false

  const providersBody = h('div', { class: 'provider-list' })
  const modelsBody = h('div', { class: 'models-body' })
  const mediaBody = h('div', { class: 'media-integrations' })
  const banner = h('div')
  const pending = state.app?.pending_import_choices ?? 0

  const sections = [
    ['providers', 'AI providers', 'key'],
    ['personality', 'Personality', 'agents'],
    ['models', 'Models', 'sliders'],
    ['narration', 'Narration', 'voice'],
    ['media', 'Stock media', 'image'],
    ['appearance', 'Appearance', 'palette'],
    ['setup', 'Setup guide', 'compass'],
    ['data', pending ? `Data (${pending} to review)` : 'Data', 'database'],
  ] as const

  function jump(id: string, smooth = true): void {
    const target = document.getElementById(`settings-${id}`)
    target?.scrollIntoView({ block: 'start', behavior: smooth && !prefersReducedMotion() ? 'smooth' : 'auto' })
    target?.querySelector<HTMLElement>('h2')?.focus({ preventScroll: true })
  }

  replace(
    outlet,
    h(
      'div',
      { class: 'page page-settings' },
      pageHeader('Settings', 'Connect AI providers, choose narration and media services, choose the orchestrator’s personality and models, and set your preferences.'),
      h(
        'div',
        { class: 'settings-layout' },
        h(
          'nav',
          { class: 'settings-nav', 'aria-label': 'Settings sections' },
          h(
            'ul',
            null,
            sections.map(([id, label, glyph]) =>
              h(
                'li',
                null,
                h(
                  'a',
                  {
                    href: `#/settings/${id}`,
                    onclick: (event: Event) => {
                      event.preventDefault()
                      history.replaceState(null, '', `#/settings/${id}`)
                      jump(id)
                    },
                  },
                  icon(glyph, 16),
                  label,
                ),
              ),
            ),
          ),
        ),
        h(
          'div',
          { class: 'settings-sections' },
          banner,
          section(
            'providers',
            'AI providers',
            'Keys are encrypted on the server and only ever shown masked. The orchestrator and its specialists use them for every AI call; nothing runs in your browser.',
            providersBody,
          ),
          section(
            'personality',
            'Orchestrator personality',
            'Choose how the orchestrator talks to you. Both personalities have the same specialists, tools and permissions.',
            personalityPicker(),
          ),
          section('models', 'Models', 'Pick the default model, optionally give the visual specialist its own, and tune generation.', modelsBody),
          section(
            'narration',
            'Narration',
            'The voice used for narrated shorts, previews and narration retries. Projects can override it. FrameFusion never switches providers on its own.',
            narrationPanel(),
          ),
          section(
            'media',
            'Stock media',
            'Optional stock photos and footage for scene images. Keys are encrypted like your AI keys and every call goes through the server. The ElevenLabs key (narration and music) is managed under Narration.',
            mediaBody,
          ),
          section('appearance', 'Appearance', 'Choose how FrameFusion looks.', themePicker()),
          section('setup', 'Setup guide', 'Walk through the first-run steps again. Nothing you already saved is reset.', setupBody()),
          section('data', 'Data', 'Review settings imported from an older database and bring over chats saved in this browser.', dataBody()),
        ),
      ),
    ),
  )
  if (params.section) {
    requestAnimationFrame(() => jump(params.section!, false))
  } else {
    focusHeading(outlet)
  }

  async function load(): Promise<void> {
    replace(providersBody, loadingState('Loading providers…'))
    replace(modelsBody, loadingState('Loading model settings…'))
    replace(mediaBody, loadingState('Loading media integrations…'))
    try {
      const [list, settings] = await Promise.all([providers.list(), providers.aiSettings()])
      if (disposed) return
      providerStates = list.providers
      encryptionConfigured = list.encryption_configured
      ai = settings
      renderBanner()
      renderProviders()
      renderModels()
      renderMedia()
    } catch (error) {
      replace(providersBody, errorState(error, () => void load()))
      replace(modelsBody)
      replace(mediaBody)
    }
  }

  function renderBanner(): void {
    replace(
      banner,
      encryptionConfigured
        ? null
        : h(
            'div',
            { class: 'notice notice-error', role: 'alert' },
            icon('alert', 20),
            h(
              'div',
              { class: 'notice-body' },
              h('strong', null, 'Key storage is not configured'),
              h('p', null, 'API keys cannot be saved until FRAMEFUSION_ENCRYPTION_KEY is set in api/.env and the API is restarted. Run `npm run setup` to generate one.'),
            ),
          ),
    )
  }

  function find(name: string): ProviderState | undefined {
    return providerStates.find((p) => p.provider === name)
  }

  function updateProvider(next: ProviderState): void {
    providerStates = providerStates.map((p) => (p.provider === next.provider ? next : p))
  }

  function renderProviders(): void {
    replace(
      providersBody,
      AI_PROVIDERS.map((name) => find(name))
        .filter((p): p is ProviderState => Boolean(p))
        .map((p) =>
          credentialCard(p, {
            encryptionConfigured,
            onChange: async (next) => {
              updateProvider(next)
              invalidateModels(next.provider)
              ai = await providers.aiSettings()
              renderModels()
              await refreshApp()
            },
          }),
        ),
    )
  }

  function renderModels(): void {
    if (!ai) return
    replace(
      modelsBody,
      modelsForm({
        ai,
        providerStates,
        onSaved: (saved) => {
          ai = saved
          renderModels()
        },
      }),
    )
  }

  function renderMedia(): void {
    const blocks = (['pexels'] as const).map((name) => {
      const provider = find(name)
      if (!provider) return null
      const panelSlot = h('div', { class: 'media-panel' })
      const paintPanel = (configured: boolean): void => {
        replace(panelSlot, pexelsPanel(configured))
      }
      paintPanel(provider.configured)
      return h(
        'div',
        { class: `media-block media-block-${name}` },
        credentialCard(provider, {
          encryptionConfigured,
          onChange: async (next) => {
            const wasConfigured = find(name)?.configured
            updateProvider(next)
            if (wasConfigured !== next.configured) paintPanel(next.configured)
            await refreshApp()
          },
        }),
        panelSlot,
      )
    })
    replace(mediaBody, blocks)
  }

  function setupBody(): HTMLElement {
    const button = h('button', { type: 'button', class: 'button' }, icon('compass', 16), 'Open the setup guide')
    button.addEventListener('click', async () => {
      button.disabled = true
      try {
        await app.onboarding({ step: 'welcome' })
        navigate('/onboarding')
      } catch (error) {
        toast(errorMessage(error), 'error')
        button.disabled = false
      }
    })
    return h('div', { class: 'form-actions form-actions-start' }, button)
  }

  function dataBody(): HTMLElement {
    return h(
      'div',
      { class: 'data-body' },
      h('h3', { class: 'subsection-title' }, 'Imported settings'),
      importChoicesPanel(),
      h('h3', { class: 'subsection-title' }, 'Chats from the browser-only version'),
      legacyBody(),
    )
  }

  function legacyBody(): HTMLElement {
    const box = h('div', { class: 'legacy' })
    let raw: string | null = null
    try {
      raw = localStorage.getItem(LEGACY_KEY)
    } catch {
      raw = null
    }
    let parsed: { chats?: unknown[] } | null = null
    if (raw) {
      try {
        parsed = JSON.parse(raw) as { chats?: unknown[] }
      } catch {
        parsed = null
      }
    }
    const chats = Array.isArray(parsed?.chats) ? parsed!.chats! : []
    if (!chats.length) {
      replace(
        box,
        h('p', { class: 'muted' }, 'No chats from the previous version were found in this browser.'),
        h(
          'p',
          { class: 'field-hint' },
          'Moved browsers? Export with ',
          h('code', null, 'copy(localStorage.getItem("framefusion:chats"))'),
          ' in the old browser’s console and run ',
          h('code', null, 'npm run manage -- import_legacy_chats --file chats.json'),
          '.',
        ),
      )
      return box
    }

    const report = h('div', { class: 'import-report', role: 'status', 'aria-live': 'polite' })
    const preview = h('button', { type: 'button', class: 'button' }, 'Preview import')
    const run = h('button', { type: 'button', class: 'button button-primary', disabled: true }, `Import ${chats.length} chat${chats.length === 1 ? '' : 's'}`)

    preview.addEventListener('click', async () => {
      preview.disabled = true
      replace(report, spinner('Checking'), ' Checking…')
      try {
        const result = await studio.importLegacy(parsed, true)
        replace(
          report,
          h('p', null, `${result.projects_created} new project${result.projects_created === 1 ? '' : 's'} with ${result.messages_created} messages would be created. ${result.projects_skipped} already imported or empty.`),
        )
        run.disabled = result.projects_created === 0
      } catch (error) {
        replace(report, h('p', { class: 'form-error' }, errorMessage(error)))
      }
      preview.disabled = false
    })

    run.addEventListener('click', async () => {
      run.disabled = true
      preview.disabled = true
      replace(report, spinner('Importing'), ' Importing…')
      try {
        const result = await studio.importLegacy(parsed, false)
        await refreshProjects()
        const removeLocal = h('button', { type: 'button', class: 'button button-small button-ghost' }, 'Remove the browser copy')
        removeLocal.addEventListener('click', async () => {
          const ok = await confirmDialog({
            title: 'Remove the old browser copy?',
            body: 'Your imported projects are safe on the server. This only clears the previous version’s copy from this browser.',
            confirm: 'Remove browser copy',
          })
          if (!ok) return
          localStorage.removeItem(LEGACY_KEY)
          replace(box, h('p', { class: 'muted' }, 'Browser copy removed. Your projects are on the server.'))
        })
        replace(
          report,
          h(
            'p',
            null,
            `Imported ${result.projects_created} project${result.projects_created === 1 ? '' : 's'} and ${result.messages_created} messages.`,
            result.media_claimed ? ` Linked ${result.media_claimed} media file${result.media_claimed === 1 ? '' : 's'}.` : '',
          ),
          h('p', { class: 'field-hint' }, 'The original data is still in this browser until you remove it.'),
          removeLocal,
        )
        toast('Chats imported.', 'success')
      } catch (error) {
        replace(report, h('p', { class: 'form-error' }, errorMessage(error)))
        run.disabled = false
      }
      preview.disabled = false
    })

    replace(
      box,
      h('p', null, `Found ${chats.length} chat${chats.length === 1 ? '' : 's'} saved by the previous version in this browser. Importing adds them as projects; nothing existing is changed and running it twice will not duplicate them.`),
      h('div', { class: 'form-actions' }, preview, run),
      report,
    )
    return box
  }

  void load()
  return () => {
    disposed = true
  }
}

function section(id: string, title: string, description: string, body: Node): HTMLElement {
  return h(
    'section',
    { class: 'settings-section', id: `settings-${id}`, 'aria-labelledby': `settings-${id}-title` },
    h('h2', { id: `settings-${id}-title`, tabindex: '-1' }, title),
    h('p', { class: 'section-description' }, description),
    body,
  )
}
