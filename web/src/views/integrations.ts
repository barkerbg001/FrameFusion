// Settings building blocks shared by the Settings page and the onboarding wizard.
import {
  app,
  imports,
  isTerminal,
  media,
  mediaUrl,
  narration,
  providers,
  type AISettings,
  type EdgeSettings,
  type EdgeVoice,
  type ElevenLabsSettings,
  type ImportChoice,
  type Job,
  type MediaSettings,
  type ModelChoice,
  type ModelsResponse,
  type NarrationPreviewConfig,
  type NarrationPreviewResult,
  type NarrationProvider,
  type NarrationProviderInfo,
  type NarrationSettings,
  type PersonalityId,
  type Route,
  type PexelsSettings,
  type ProviderName,
  type ProviderState,
  type SpeechModel,
  type Theme,
  type Voice,
  type VoiceSettings,
} from '../api.ts'
import { avatar, PERSONALITIES, PERSONALITY_IDS } from '../avatars.ts'
import { h, icon, relativeTime, replace, spinner } from '../dom.ts'
import { watchJob, type JobWatcher } from '../jobs.ts'
import { refreshApp, state } from '../state.ts'
import { applyTheme, currentTheme } from '../theme.ts'
import { toast } from '../toast.ts'
import { confirmDialog, errorMessage, errorState, loadingState } from './common.ts'

export const AI_PROVIDERS: ProviderName[] = ['openrouter', 'gemini', 'anthropic']

const STATUS_TEXT: Record<string, string> = {
  unconfigured: 'Not set up',
  configured: 'Saved, not tested',
  testing: 'Testing…',
  valid: 'Connected',
  failed: 'Connection failed',
}

function externalLink(href: string, label: string): HTMLElement {
  return h('a', { class: 'link', href, target: '_blank', rel: 'noopener noreferrer' }, label, icon('external', 12))
}

// --- API key card -------------------------------------------------------------------------

export interface CredentialCardOptions {
  encryptionConfigured: boolean
  onChange?: (next: ProviderState) => void | Promise<void>
}

export function credentialCard(initial: ProviderState, options: CredentialCardOptions): HTMLElement {
  let provider = initial
  let status: string = provider.status
  const inputId = `key-${provider.provider}`
  const resultId = `key-result-${provider.provider}`
  const keyInput = h('input', {
    id: inputId,
    type: 'password',
    // API keys are not login passwords; this stops browsers pairing nearby fields with saved logins.
    autocomplete: 'new-password',
    spellcheck: 'false',
    autocapitalize: 'none',
    placeholder: provider.configured ? 'Enter a new key to replace the saved one' : provider.key_prefix_hint,
    maxlength: 512,
    'aria-describedby': resultId,
    'data-1p-ignore': true,
    'data-lpignore': 'true',
  })
  const reveal = h(
    'button',
    { type: 'button', class: 'icon-button input-addon', 'aria-label': 'Show key', 'aria-pressed': 'false', 'aria-controls': inputId },
    icon('eye', 16),
  )
  reveal.addEventListener('click', () => {
    const showing = keyInput.type === 'text'
    keyInput.type = showing ? 'password' : 'text'
    reveal.setAttribute('aria-pressed', String(!showing))
    reveal.setAttribute('aria-label', showing ? 'Show key' : 'Hide key')
    replace(reveal, icon(showing ? 'eye' : 'eyeOff', 16))
  })

  const badge = h('span', { class: 'badge' })
  const result = h('p', { class: 'provider-result', id: resultId, role: 'status', 'aria-live': 'polite' })
  const saveButton = h('button', { type: 'submit', class: 'button button-primary button-small' }, 'Save key')
  const testButton = h('button', { type: 'button', class: 'button button-small' }, 'Test connection')
  const removeButton = h('button', { type: 'button', class: 'button button-small button-ghost danger' }, icon('trash', 14), 'Remove')
  const saved = h('div', { class: 'saved-key' })

  function paint(): void {
    badge.className = `badge badge-${status}`
    replace(badge, status === 'testing' ? spinner('Testing') : null, STATUS_TEXT[status] ?? status)
    const typed = keyInput.value.trim().length > 0
    saveButton.disabled = !typed || !options.encryptionConfigured || status === 'testing'
    testButton.disabled = (!typed && !provider.configured) || status === 'testing'
    removeButton.hidden = !provider.configured
    testButton.textContent = typed && provider.configured ? 'Test new key' : 'Test connection'
    keyInput.placeholder = provider.configured ? 'Enter a new key to replace the saved one' : provider.key_prefix_hint
    replace(
      saved,
      provider.configured
        ? [
            icon('key', 14),
            h('code', { 'aria-label': `Saved key ending in ${provider.masked_key?.replace(/•/g, '') || 'hidden'}` }, provider.masked_key ?? '••••'),
            h('span', { class: 'muted' }, provider.last_tested_at ? `Tested ${relativeTime(provider.last_tested_at)}` : `Saved ${relativeTime(provider.updated_at)}`),
          ]
        : h('span', { class: 'muted' }, 'No key saved'),
    )
  }

  function showResult(ok: boolean, message: string): void {
    result.className = `provider-result ${ok ? 'ok' : 'fail'}`
    replace(result, icon(ok ? 'check' : 'alert', 14), h('span', null, message))
  }

  async function changed(): Promise<void> {
    try {
      await options.onChange?.(provider)
    } catch {
      // The card already shows the outcome; dependent panels refresh on next load.
    }
  }

  keyInput.addEventListener('input', paint)

  const form = h(
    'form',
    { class: 'provider-form' },
    h('label', { for: inputId }, provider.configured ? 'Replace API key' : 'API key'),
    h('div', { class: 'input-group' }, keyInput, reveal),
    h('div', { class: 'provider-actions' }, saveButton, testButton, removeButton),
  )

  async function runTest(unsavedKey?: string): Promise<void> {
    status = 'testing'
    paint()
    try {
      const response = await providers.test(provider.provider, unsavedKey)
      if (response.tested === 'saved_key') provider = response.provider
      status = provider.status
      const prefix = response.tested === 'unsaved_key' ? 'New key (not saved): ' : ''
      showResult(response.result.ok, `${prefix}${response.result.message}`)
    } catch (error) {
      status = provider.status
      showResult(false, errorMessage(error))
    }
    paint()
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault()
    const key = keyInput.value.trim()
    if (!key) return
    saveButton.disabled = true
    try {
      provider = await providers.saveKey(provider.provider, key)
      keyInput.value = ''
      keyInput.type = 'password'
      status = provider.status
      paint()
      toast(`${provider.label} key saved.`, 'success')
      await runTest()
      await changed()
    } catch (error) {
      showResult(false, errorMessage(error))
      paint()
    }
  })

  testButton.addEventListener('click', () => {
    const key = keyInput.value.trim()
    void runTest(key || undefined).then(() => {
      if (!key) void changed()
    })
  })

  removeButton.addEventListener('click', async () => {
    const ok = await confirmDialog({
      title: `Remove the ${provider.label} key?`,
      body:
        provider.kind === 'ai'
          ? 'Agents that use this provider will stop working until you add a key again.'
          : `${provider.features} will be unavailable until you add a key again.`,
      confirm: 'Remove key',
      danger: true,
    })
    if (!ok) return
    try {
      provider = await providers.removeKey(provider.provider)
      status = provider.status
      replace(result)
      paint()
      toast(`${provider.label} key removed.`)
      await changed()
    } catch (error) {
      showResult(false, errorMessage(error))
    }
  })

  if (provider.last_test_message && provider.status === 'failed') {
    showResult(false, provider.last_test_message)
  }
  paint()

  return h(
    'article',
    { class: `provider-card provider-${provider.provider}` },
    h(
      'header',
      { class: 'provider-head' },
      h('div', null, h('h3', null, provider.label), h('p', { class: 'provider-features' }, provider.features), saved),
      badge,
    ),
    form,
    result,
    h(
      'p',
      { class: 'provider-note' },
      provider.test_billing_note,
      ' ',
      externalLink(provider.key_url, 'Get a key'),
      ' · ',
      externalLink(provider.docs_url, 'Docs'),
    ),
  )
}

// --- Models and agents --------------------------------------------------------------------

const modelCache = new Map<ProviderName, ModelsResponse>()

export function invalidateModels(provider?: string): void {
  if (provider) modelCache.delete(provider as ProviderName)
  else modelCache.clear()
}

async function loadModels(provider: ProviderName, refresh = false): Promise<ModelsResponse> {
  const cached = modelCache.get(provider)
  if (cached && !refresh) return cached
  const response = await providers.models(provider, refresh)
  modelCache.set(provider, response)
  return response
}

export interface ModelsFormOptions {
  ai: AISettings
  providerStates: ProviderState[]
  submitLabel?: string
  onSaved?: (ai: AISettings) => void | Promise<void>
}

export function modelsForm(options: ModelsFormOptions): HTMLElement {
  const settings = options.ai
  const providerLabel = (name: ProviderName): string =>
    options.providerStates.find((p) => p.provider === name)?.label ?? name
  const providerConfigured = (name: ProviderName): boolean =>
    Boolean(options.providerStates.find((p) => p.provider === name)?.configured)

  // A provider <select> plus a model picker fed by live discovery (or the fallback list).
  function modelChooser(idPrefix: string, initial: ModelChoice | null, onChange: (choice: ModelChoice | null) => void): HTMLElement {
    let provider: ProviderName | null = initial?.provider ?? null
    let model = initial?.model ?? ''

    const providerSelect = h(
      'select',
      { id: `${idPrefix}-provider` },
      h('option', { value: '' }, 'Choose a provider'),
      AI_PROVIDERS.map((name) =>
        h('option', { value: name, selected: name === provider }, `${providerLabel(name)}${providerConfigured(name) ? '' : ' (no key yet)'}`),
      ),
    )
    const modelSelect = h('select', { id: `${idPrefix}-model` })
    const customInput = h('input', {
      id: `${idPrefix}-custom`,
      placeholder: 'Exact model ID',
      maxlength: 200,
      spellcheck: 'false',
      autocapitalize: 'none',
      hidden: true,
      'aria-label': 'Custom model ID',
    })
    const refresh = h(
      'button',
      { type: 'button', class: 'icon-button', 'aria-label': 'Refresh model list', title: 'Refresh model list' },
      icon('refresh', 16),
    )
    const note = h('p', { class: 'field-hint' })
    const warn = h('p', { class: 'field-warn', hidden: true })

    function emit(): void {
      onChange(provider && model ? { provider, model } : null)
      warn.hidden = !provider || providerConfigured(provider)
      if (provider && !providerConfigured(provider)) {
        replace(warn, icon('alert', 14), `Add a ${providerLabel(provider)} key before this can run.`)
      }
    }

    async function fillModels(force = false): Promise<void> {
      if (!provider) {
        replace(modelSelect, h('option', { value: '' }, 'Choose a provider first'))
        modelSelect.disabled = true
        refresh.disabled = true
        customInput.hidden = true
        replace(note)
        emit()
        return
      }
      modelSelect.disabled = true
      refresh.disabled = true
      replace(modelSelect, h('option', { value: '' }, 'Loading models…'))
      replace(note, spinner('Loading models'), ' Loading models…')
      try {
        const response = await loadModels(provider, force)
        const ids = response.models.map((m) => m.id)
        const custom = Boolean(model) && !ids.includes(model)
        replace(
          modelSelect,
          h('option', { value: '' }, 'Choose a model'),
          response.models.map((m) =>
            h('option', { value: m.id, selected: m.id === model }, m.label && m.label !== m.id ? `${m.label} — ${m.id}` : m.id),
          ),
          h('option', { value: '__custom__', selected: custom }, 'Custom model ID…'),
        )
        customInput.hidden = !custom
        if (custom) customInput.value = model
        replace(
          note,
          response.source === 'live'
            ? `${response.models.length} models listed by the provider. Listing models is free; usage is billed when the orchestrator or a specialist runs.`
            : `Showing the configured fallback list. ${response.error ?? ''}`,
        )
      } catch (error) {
        replace(modelSelect, h('option', { value: '' }, 'Could not load models'), h('option', { value: '__custom__' }, 'Custom model ID…'))
        replace(note, errorMessage(error))
      }
      modelSelect.disabled = false
      refresh.disabled = false
      emit()
    }

    providerSelect.addEventListener('change', () => {
      provider = (providerSelect.value || null) as ProviderName | null
      model = ''
      void fillModels()
    })
    modelSelect.addEventListener('change', () => {
      if (modelSelect.value === '__custom__') {
        customInput.hidden = false
        model = customInput.value.trim()
        customInput.focus()
      } else {
        customInput.hidden = true
        model = modelSelect.value
      }
      emit()
    })
    customInput.addEventListener('input', () => {
      model = customInput.value.trim()
      emit()
    })
    refresh.addEventListener('click', () => void fillModels(true))

    void fillModels()

    return h(
      'div',
      { class: 'model-chooser' },
      h('div', { class: 'field' }, h('label', { for: `${idPrefix}-provider` }, 'Provider'), providerSelect),
      h(
        'div',
        { class: 'field' },
        h('label', { for: `${idPrefix}-model` }, 'Model'),
        h('div', { class: 'input-group' }, modelSelect, refresh),
        customInput,
        note,
        warn,
      ),
    )
  }

  let defaultChoice: ModelChoice | null = settings.default_provider
    ? { provider: settings.default_provider, model: settings.default_model }
    : null
  const overrides: Record<Route, ModelChoice | null> = { ...settings.overrides }
  const useOverride: Record<Route, boolean> = {
    planner: Boolean(settings.overrides.planner),
    production: Boolean(settings.overrides.production),
  }

  const temperatureOn = h('input', { type: 'checkbox', id: 'temp-on', checked: settings.temperature !== null })
  const temperature = h('input', { type: 'range', id: 'temp', min: 0, max: 2, step: 0.1, value: settings.temperature ?? 0.7, 'aria-describedby': 'temp-hint' })
  const temperatureValue = h('output', { for: 'temp', class: 'range-value' })
  const tokensOn = h('input', { type: 'checkbox', id: 'tokens-on', checked: settings.max_output_tokens !== null })
  const tokens = h('input', {
    type: 'number',
    id: 'tokens',
    min: 256,
    max: 65536,
    step: 256,
    value: settings.max_output_tokens ?? 4096,
    inputmode: 'numeric',
    'aria-describedby': 'tokens-hint',
  })
  const tempHint = h('p', { class: 'field-hint', id: 'temp-hint' })
  const generation = h('div', { class: 'generation' })
  const saveButton = h('button', { type: 'submit', class: 'button button-primary' }, options.submitLabel ?? 'Save model settings')
  const formError = h('p', { class: 'form-error', role: 'alert', hidden: true })

  function chosenProviders(): ProviderName[] {
    const list = new Set<ProviderName>()
    if (defaultChoice) list.add(defaultChoice.provider)
    for (const persona of ['planner', 'production'] as const) {
      const choice = overrides[persona]
      if (useOverride[persona] && choice) list.add(choice.provider)
    }
    return [...list]
  }

  function paintGeneration(): void {
    const chosen = chosenProviders()
    const caps = chosen.map((p) => settings.capabilities[p])
    const supportsTemperature = caps.length > 0 && caps.every((c) => c?.temperature)
    const supportsTokens = caps.length > 0 && caps.every((c) => c?.max_output_tokens)
    temperatureValue.textContent = Number(temperature.value).toFixed(1)
    temperature.disabled = !temperatureOn.checked
    tokens.disabled = !tokensOn.checked
    tempHint.textContent = chosen.includes('anthropic')
      ? `Claude accepts up to ${settings.notes.anthropic_temperature_max.toFixed(1)}; higher values are capped for Claude calls.`
      : 'Lower is more focused, higher is more varied. Off uses each agent’s tuned default.'

    const parts: Node[] = []
    if (!chosen.length) {
      parts.push(h('p', { class: 'muted' }, 'Choose a provider above to see the generation controls it supports.'))
    }
    if (supportsTemperature) {
      parts.push(
        h(
          'div',
          { class: 'field' },
          h('label', { class: 'check' }, temperatureOn, h('span', null, 'Override temperature')),
          h('div', { class: 'range-row' }, h('label', { for: 'temp', class: 'sr-only' }, 'Temperature'), temperature, temperatureValue),
          tempHint,
        ),
      )
    }
    if (supportsTokens) {
      parts.push(
        h(
          'div',
          { class: 'field' },
          h('label', { class: 'check' }, tokensOn, h('span', null, 'Limit response length')),
          h('div', { class: 'range-row' }, h('label', { for: 'tokens', class: 'sr-only' }, 'Maximum output tokens'), tokens, h('span', { class: 'muted' }, 'tokens')),
          h('p', { class: 'field-hint', id: 'tokens-hint' }, 'Upper bound per model call. Off uses each agent’s default.'),
        ),
      )
    }
    replace(generation, parts)
  }

  temperatureOn.addEventListener('change', paintGeneration)
  tokensOn.addEventListener('change', paintGeneration)
  temperature.addEventListener('input', () => {
    temperatureValue.textContent = Number(temperature.value).toFixed(1)
  })

  function overrideBlock(persona: Route): HTMLElement {
    const info = settings.readiness[persona]
    const toggle = h('input', { type: 'checkbox', id: `override-${persona}`, checked: useOverride[persona] })
    const chooserSlot = h('div', { class: 'override-chooser', hidden: !useOverride[persona] })
    chooserSlot.appendChild(
      modelChooser(`override-${persona}`, overrides[persona], (choice) => {
        overrides[persona] = choice
        paintGeneration()
      }),
    )
    toggle.addEventListener('change', () => {
      useOverride[persona] = toggle.checked
      chooserSlot.hidden = !toggle.checked
      paintGeneration()
    })
    const readiness = settings.readiness[persona]
    return h(
      'div',
      { class: `override override-${persona}` },
      h(
        'div',
        { class: 'override-head' },
        h('span', { class: 'route-icon', 'aria-hidden': 'true' }, icon(persona === 'planner' ? 'workflow' : 'image', 18)),
        h(
          'div',
          null,
          h('strong', null, info.name, h('span', { class: 'role-tag' }, persona === 'planner' ? 'Chat, planning, script' : 'Scene images and visual plan')),
          h(
            'p',
            { class: readiness.ready ? 'muted' : 'field-warn' },
            readiness.ready ? `Currently ${readiness.provider_label} · ${readiness.model}` : (readiness.problem ?? ''),
          ),
        ),
      ),
      h('label', { class: 'check' }, toggle, h('span', null, `Use a different model for ${info.name}`)),
      chooserSlot,
    )
  }

  const form = h(
    'form',
    { class: 'models-form' },
    h(
      'fieldset',
      null,
      h('legend', null, 'Default model'),
      h('p', { class: 'field-hint' }, 'Used by the orchestrator and its specialists unless you override a route below. Both personalities use the same models. FrameFusion never switches providers on its own.'),
      modelChooser('default', defaultChoice, (choice) => {
        defaultChoice = choice
        paintGeneration()
      }),
    ),
    h('fieldset', null, h('legend', null, 'Per-route models'), overrideBlock('planner'), overrideBlock('production')),
    h('fieldset', null, h('legend', null, 'Generation'), generation),
    formError,
    h('div', { class: 'form-actions' }, saveButton),
  )

  form.addEventListener('submit', async (event) => {
    event.preventDefault()
    formError.hidden = true
    for (const persona of ['planner', 'production'] as const) {
      if (useOverride[persona] && !overrides[persona]) {
        formError.textContent = `Choose a provider and model for ${settings.readiness[persona].name}, or turn the override off.`
        formError.hidden = false
        return
      }
    }
    saveButton.disabled = true
    replace(saveButton, spinner('Saving'), ' Saving…')
    try {
      const saved = await providers.saveAISettings({
        default_provider: defaultChoice?.provider ?? null,
        default_model: defaultChoice?.model ?? '',
        temperature: temperatureOn.checked ? Number(temperature.value) : null,
        max_output_tokens: tokensOn.checked ? Number(tokens.value) : null,
        overrides: {
          planner: useOverride.planner ? overrides.planner : null,
          production: useOverride.production ? overrides.production : null,
        },
      })
      await refreshApp()
      toast('Model settings saved.', 'success')
      await options.onSaved?.(saved)
    } catch (error) {
      formError.textContent = errorMessage(error)
      formError.hidden = false
    }
    saveButton.disabled = false
    replace(saveButton, options.submitLabel ?? 'Save model settings')
  })

  paintGeneration()
  return form
}

// --- Appearance ---------------------------------------------------------------------------

export function themePicker(): HTMLElement {
  const choices: { value: Theme; label: string; icon: string }[] = [
    { value: 'system', label: 'System', icon: 'monitor' },
    { value: 'dark', label: 'Dark', icon: 'moon' },
    { value: 'light', label: 'Light', icon: 'sun' },
  ]
  const selected = state.app?.theme ?? currentTheme()
  const group = h(
    'div',
    { class: 'theme-options', role: 'radiogroup', 'aria-label': 'Theme' },
    choices.map((option) => {
      const input = h('input', { type: 'radio', name: 'theme', value: option.value, checked: option.value === selected })
      input.addEventListener('change', async () => {
        applyTheme(option.value)
        try {
          await app.setTheme(option.value)
          if (state.app) state.app.theme = option.value
        } catch (error) {
          toast(`Theme applied here but not saved: ${errorMessage(error)}`, 'error')
        }
      })
      return h(
        'label',
        { class: 'theme-option' },
        input,
        h('span', { class: `theme-swatch swatch-${option.value}`, 'aria-hidden': 'true' }),
        h('span', { class: 'theme-label' }, icon(option.icon, 16), option.label),
      )
    }),
  )
  return h('div', null, group, h('p', { class: 'field-hint' }, 'System follows your device setting. Motion is reduced automatically when your device asks for it.'))
}

// --- Orchestrator personality ---------------------------------------------------------------

export function personalityPicker(options: { onSaved?: (id: PersonalityId) => void } = {}): HTMLElement {
  const selected = state.app?.personality ?? 'director'
  const group = h(
    'div',
    { class: 'personality-options', role: 'radiogroup', 'aria-label': 'Default personality' },
    PERSONALITY_IDS.map((id) => {
      const info = PERSONALITIES[id]
      const input = h('input', { type: 'radio', name: 'personality', value: id, checked: id === selected })
      input.addEventListener('change', async () => {
        try {
          await app.setPersonality(id)
          if (state.app) state.app.personality = id
          toast(`${info.name} is now the default personality. Running work finishes first.`, 'success')
          options.onSaved?.(id)
        } catch (error) {
          toast(`Personality not saved: ${errorMessage(error)}`, 'error')
        }
      })
      return h(
        'label',
        { class: `personality-option tone-${info.tone}` },
        input,
        avatar(id, { size: 'sm' }),
        h('span', { class: 'personality-text' }, h('strong', null, info.name), h('span', { class: 'muted' }, info.summary)),
      )
    }),
  )
  return h(
    'div',
    null,
    group,
    h(
      'p',
      { class: 'field-hint' },
      'One orchestrator plans and runs every project. The personality changes only its voice: both have the same specialists, tools, models and permissions. Projects can override this, and a change applies from the next turn.',
    ),
  )
}

// --- ElevenLabs ---------------------------------------------------------------------------

const DEFAULT_VOICE_SETTINGS: Required<{ [K in keyof VoiceSettings]: NonNullable<VoiceSettings[K]> }> = {
  stability: 0.5,
  similarity_boost: 0.75,
  style: 0,
  speed: 1,
  use_speaker_boost: true,
}

function voiceMeta(voice: Voice): string {
  const labels = ['gender', 'age', 'accent', 'use_case', 'descriptive']
    .map((key) => voice.labels[key])
    .filter((value): value is string => Boolean(value))
    .map((value) => value.replace(/_/g, ' '))
  if (voice.category) labels.push(voice.category)
  return labels.join(' · ')
}

export function elevenLabsPanel(configured: boolean, options: { onSaved?: () => void } = {}): HTMLElement {
  const root = h('div', { class: 'media-settings media-settings-elevenlabs' })
  if (!configured) {
    replace(
      root,
      h('p', { class: 'muted' }, 'Save an ElevenLabs key above to choose a narrator voice, speech model and music model.'),
    )
    return root
  }
  replace(root, loadingState('Loading ElevenLabs settings…'))

  const sampleAudio = new Audio()
  sampleAudio.preload = 'none'
  let playingId: string | null = null

  async function load(): Promise<void> {
    try {
      const [settings, models] = await Promise.all([media.settings(), media.models()])
      render(settings, models.models)
    } catch (error) {
      replace(root, errorState(error, () => void load()))
    }
  }

  function render(saved: MediaSettings, models: SpeechModel[]): void {
    const draft: ElevenLabsSettings = structuredClone(saved.elevenlabs)
    const customised = Object.values(draft.voice_settings).some((value) => value !== null)

    // Voice picker -------------------------------------------------------------------
    const selectedLabel = h('p', { class: 'voice-selected', 'aria-live': 'polite' })
    const searchInput = h('input', { type: 'search', id: 'voice-search', placeholder: 'Search voices by name, accent or style', maxlength: 100, autocomplete: 'off', 'data-1p-ignore': '', 'data-lpignore': 'true' })
    const searchButton = h('button', { type: 'submit', class: 'button button-small' }, 'Search')
    const list = h('ul', { class: 'voice-list', role: 'radiogroup', 'aria-label': 'Voices' })
    const more = h('button', { type: 'button', class: 'button button-small button-ghost', hidden: true }, 'Load more voices')
    const listStatus = h('p', { class: 'field-hint', role: 'status' })
    let nextToken: string | null = null
    let query = ''

    function paintSelected(): void {
      replace(
        selectedLabel,
        draft.voice_id
          ? [icon('check', 14), h('span', null, 'Selected: '), h('strong', null, draft.voice_name || draft.voice_id)]
          : h('span', { class: 'field-warn' }, 'No voice selected. Narration uses the ElevenLabs default voice until you pick one.'),
      )
    }

    function playSample(voice: Voice, button: HTMLButtonElement): void {
      if (playingId === voice.voice_id && !sampleAudio.paused) {
        sampleAudio.pause()
        return
      }
      sampleAudio.src = voice.preview_url
      playingId = voice.voice_id
      for (const other of list.querySelectorAll<HTMLButtonElement>('.voice-play')) {
        other.setAttribute('aria-pressed', 'false')
      }
      button.setAttribute('aria-pressed', 'true')
      sampleAudio.play().catch(() => toast('Could not play this sample.', 'error'))
    }

    sampleAudio.onended = sampleAudio.onpause = () => {
      for (const button of list.querySelectorAll<HTMLButtonElement>('.voice-play')) {
        button.setAttribute('aria-pressed', 'false')
      }
    }

    function voiceItem(voice: Voice): HTMLElement {
      const radio = h('input', { type: 'radio', name: 'elevenlabs-voice', value: voice.voice_id, checked: voice.voice_id === draft.voice_id })
      radio.addEventListener('change', () => {
        draft.voice_id = voice.voice_id
        draft.voice_name = voice.name
        paintSelected()
      })
      const play = h(
        'button',
        { type: 'button', class: 'icon-button voice-play', 'aria-label': `Play the free ElevenLabs sample for ${voice.name}`, 'aria-pressed': 'false', title: 'Play sample' },
        icon('play', 16),
      )
      play.addEventListener('click', () => playSample(voice, play))
      return h(
        'li',
        { class: 'voice-item' },
        h('label', { class: 'voice-option' }, radio, h('span', { class: 'voice-text' }, h('span', { class: 'voice-name' }, voice.name), h('span', { class: 'voice-meta' }, voiceMeta(voice)))),
        voice.preview_url ? play : null,
      )
    }

    async function fetchVoices(reset: boolean): Promise<void> {
      searchButton.disabled = true
      more.disabled = true
      if (reset) {
        replace(list)
        nextToken = null
      }
      replace(listStatus, spinner('Loading voices'), ' Loading voices…')
      try {
        const page = await media.voices(query, reset ? null : nextToken)
        list.append(...page.voices.map(voiceItem))
        nextToken = page.next_page_token
        more.hidden = !page.has_more
        replace(
          listStatus,
          list.children.length
            ? `${list.children.length} voice${list.children.length === 1 ? '' : 's'} shown. Samples are ElevenLabs’ own recordings and cost nothing to play.`
            : query
              ? `No voices match “${query}”.`
              : 'No voices found on this ElevenLabs account.',
        )
      } catch (error) {
        replace(listStatus, h('span', { class: 'form-error' }, errorMessage(error)))
      }
      searchButton.disabled = false
      more.disabled = false
    }

    const searchForm = h(
      'form',
      { class: 'voice-search', role: 'search' },
      h('label', { for: 'voice-search', class: 'sr-only' }, 'Search voices'),
      searchInput,
      searchButton,
    )
    searchForm.addEventListener('submit', (event) => {
      event.preventDefault()
      query = searchInput.value.trim()
      void fetchVoices(true)
    })
    more.addEventListener('click', () => void fetchVoices(false))

    // Models ---------------------------------------------------------------------------
    const modelSelect = h(
      'select',
      { id: 'elevenlabs-model' },
      models.map((m) => h('option', { value: m.model_id, selected: m.model_id === draft.model_id }, m.name)),
      models.some((m) => m.model_id === draft.model_id) ? null : h('option', { value: draft.model_id, selected: true }, draft.model_id),
    )
    modelSelect.addEventListener('change', () => {
      draft.model_id = modelSelect.value
    })
    const modelHint = models[0]?.source === 'fallback' ? 'This key cannot list models, so common ElevenLabs models are shown.' : 'Models available to this ElevenLabs account.'

    const musicSelect = h(
      'select',
      { id: 'elevenlabs-music' },
      saved.music_models.map((m) => h('option', { value: m.model_id, selected: m.model_id === draft.music_model }, m.name)),
    )
    musicSelect.addEventListener('change', () => {
      draft.music_model = musicSelect.value
    })

    // Voice settings -------------------------------------------------------------------
    const customToggle = h('input', { type: 'checkbox', id: 'voice-custom', checked: customised })
    const sliders = h('div', { class: 'slider-grid', hidden: !customised })
    const values = { ...DEFAULT_VOICE_SETTINGS }
    for (const key of Object.keys(values) as (keyof VoiceSettings)[]) {
      const current = draft.voice_settings[key]
      if (current !== null && current !== undefined) (values as Record<string, number | boolean>)[key] = current
    }

    function slider(key: 'stability' | 'similarity_boost' | 'style' | 'speed', label: string, hint: string, min: number, max: number, step: number): HTMLElement {
      const id = `voice-${key}`
      const input = h('input', { type: 'range', id, min, max, step, value: values[key], 'aria-describedby': `${id}-hint` })
      const output = h('output', { for: id, class: 'range-value' }, values[key].toFixed(2))
      input.addEventListener('input', () => {
        values[key] = Number(input.value)
        output.textContent = values[key].toFixed(2)
      })
      return h(
        'div',
        { class: 'field' },
        h('label', { for: id }, label),
        h('div', { class: 'range-row' }, input, output),
        h('p', { class: 'field-hint', id: `${id}-hint` }, hint),
      )
    }

    const boost = h('input', { type: 'checkbox', id: 'voice-boost', checked: values.use_speaker_boost })
    boost.addEventListener('change', () => {
      values.use_speaker_boost = boost.checked
    })
    sliders.append(
      slider('stability', 'Stability', 'Lower is more expressive, higher is more consistent.', 0, 1, 0.05),
      slider('similarity_boost', 'Similarity', 'How closely the output follows the original voice.', 0, 1, 0.05),
      slider('style', 'Style exaggeration', 'Amplifies the speaker’s style. Higher values can add latency.', 0, 1, 0.05),
      slider('speed', 'Speed', '1.00 is normal speed.', 0.7, 1.2, 0.05),
      h('label', { class: 'check' }, boost, h('span', null, 'Speaker boost (closer to the original voice)')),
    )
    customToggle.addEventListener('change', () => {
      sliders.hidden = !customToggle.checked
    })

    function voiceSettings(): VoiceSettings {
      if (!customToggle.checked) {
        return { stability: null, similarity_boost: null, style: null, speed: null, use_speaker_boost: null }
      }
      return { ...values }
    }

    // Save -----------------------------------------------------------------------------
    const saveButton = h('button', { type: 'submit', class: 'button button-primary' }, 'Save voice settings')
    const formError = h('p', { class: 'form-error', role: 'alert', hidden: true })
    const form = h(
      'form',
      { class: 'media-form' },
      h(
        'fieldset',
        null,
        h('legend', null, 'Narrator voice'),
        selectedLabel,
        searchForm,
        list,
        listStatus,
        more,
      ),
      h(
        'fieldset',
        null,
        h('legend', null, 'Models'),
        h('div', { class: 'field' }, h('label', { for: 'elevenlabs-model' }, 'Speech model'), modelSelect, h('p', { class: 'field-hint' }, modelHint)),
        h('div', { class: 'field' }, h('label', { for: 'elevenlabs-music' }, 'Music model'), musicSelect, h('p', { class: 'field-hint' }, 'Used when you ask the music specialist for a standalone track. Production music beds are generated locally.')),
      ),
      h(
        'fieldset',
        null,
        h('legend', null, 'Voice settings'),
        h('label', { class: 'check' }, customToggle, h('span', null, 'Fine-tune the voice (otherwise the voice’s own defaults are used)')),
        sliders,
      ),
      h(
        'div',
        { class: 'notice notice-warn credit-notice' },
        icon('info', 16),
        h('p', null, 'Previews and narrated shorts with ElevenLabs use your ElevenLabs credits for every character. Save these settings, then use the narration preview below; it only runs when you click it.'),
      ),
      formError,
      h('div', { class: 'form-actions' }, saveButton),
    )
    form.addEventListener('submit', async (event) => {
      event.preventDefault()
      formError.hidden = true
      saveButton.disabled = true
      try {
        const next = await media.saveElevenLabs({ ...draft, voice_settings: voiceSettings() })
        Object.assign(draft, next.elevenlabs)
        toast('ElevenLabs voice settings saved.', 'success')
        options.onSaved?.()
      } catch (error) {
        formError.textContent = errorMessage(error)
        formError.hidden = false
      }
      saveButton.disabled = false
    })

    paintSelected()
    replace(root, form)
    void fetchVoices(true)
  }

  void load()
  return root
}

// --- Narration ----------------------------------------------------------------------------

let edgeVoiceCache: EdgeVoice[] | null = null

export async function loadEdgeVoices(refresh = false): Promise<EdgeVoice[]> {
  if (edgeVoiceCache && !refresh) return edgeVoiceCache
  edgeVoiceCache = (await narration.edgeVoices(refresh)).voices
  return edgeVoiceCache
}

export function edgeVoiceMeta(voice: EdgeVoice): string {
  return [voice.locale_name, voice.gender, voice.personalities.slice(0, 2).join(', ')].filter(Boolean).join(' · ')
}

export function signed(value: number, unit: string): string {
  return `${value > 0 ? '+' : ''}${value}${unit}`
}

export function narrationSummary(provider: NarrationProvider, voiceLabel: string, voice: string): string {
  const name = provider === 'edge' ? 'Free — Edge TTS' : 'ElevenLabs'
  const who = voiceLabel || voice
  return who ? `${name} · ${who}` : name
}

const VOICE_LIST_LIMIT = 60
const SAMPLE_TEXT = 'Here is how the narration for your next short will sound.'

export interface NarrationPanelOptions {
  submitLabel?: string
  onSaved?: (settings: NarrationSettings) => void | Promise<void>
}

// One panel for Settings → Narration and the onboarding step: provider choice, voice,
// controls, an on-demand preview and the saved default used by every production.
export function narrationPanel(options: NarrationPanelOptions = {}): HTMLElement {
  const root = h('div', { class: 'narration-panel' })
  replace(root, loadingState('Loading narration settings…'))

  async function load(): Promise<void> {
    try {
      const [settings, providerList] = await Promise.all([narration.settings(), providers.list()])
      render(settings, providerList.providers.find((p) => p.provider === 'elevenlabs') ?? null, providerList.encryption_configured)
    } catch (error) {
      replace(root, errorState(error, () => void load()))
    }
  }

  function render(saved: NarrationSettings, elevenlabs: ProviderState | null, encryptionConfigured: boolean): void {
    let current = saved
    let provider: NarrationProvider = saved.provider
    const edge: EdgeSettings = { ...saved.edge }
    let elevenConfigured = Boolean(elevenlabs?.configured)
    const info = (id: NarrationProvider): NarrationProviderInfo | undefined => current.providers.find((p) => p.id === id)

    // Provider choice --------------------------------------------------------------------
    const providerGroup = h('div', { class: 'provider-choice', role: 'radiogroup', 'aria-label': 'Narration provider' })
    const disclosure = h('div', { class: 'notice notice-info narration-disclosure' })

    function providerOption(id: NarrationProvider): HTMLElement {
      const radio = h('input', { type: 'radio', name: 'narration-provider', value: id, checked: provider === id })
      radio.addEventListener('change', () => {
        provider = id
        paint()
      })
      const tags =
        id === 'edge'
          ? [tag('Free'), tag('No key'), tag('Online')]
          : [tag('API key'), tag('Uses credits'), tag(elevenConfigured ? 'Key saved' : 'No key yet', elevenConfigured ? 'ok' : 'warn')]
      return h(
        'label',
        { class: `choice-card choice-${id}` },
        radio,
        h('span', { class: 'choice-icon', 'aria-hidden': 'true' }, icon(id === 'edge' ? 'globe' : 'key', 20)),
        h(
          'span',
          { class: 'choice-body' },
          h('span', { class: 'choice-title' }, info(id)?.label ?? id),
          h('span', { class: 'choice-text' }, id === 'edge' ? 'Microsoft neural voices through the edge-tts client.' : 'Premium voices billed to your ElevenLabs account.'),
          h('span', { class: 'tag-row' }, tags),
        ),
      )
    }

    function tag(text: string, tone = ''): HTMLElement {
      return h('span', { class: `tag${tone ? ` tag-${tone}` : ''}` }, text)
    }

    // Edge voice picker -----------------------------------------------------------------
    const edgeSection = h('section', { class: 'narration-section', 'aria-labelledby': 'edge-voice-title' })
    const voiceSearch = h('input', { type: 'search', id: 'edge-voice-search', placeholder: 'Search by name, language or style', maxlength: 80, autocomplete: 'off', 'data-1p-ignore': '', 'data-lpignore': 'true' })
    const languageSelect = h('select', { id: 'edge-voice-language', 'aria-label': 'Language' }, h('option', { value: '' }, 'All languages'))
    const genderSelect = h(
      'select',
      { id: 'edge-voice-gender', 'aria-label': 'Voice type' },
      h('option', { value: '' }, 'Any voice'),
      h('option', { value: 'Female' }, 'Female'),
      h('option', { value: 'Male' }, 'Male'),
    )
    const refreshVoices = h('button', { type: 'button', class: 'icon-button', 'aria-label': 'Reload the voice list', title: 'Reload the voice list' }, icon('refresh', 16))
    const voiceList = h('ul', { class: 'voice-list', role: 'radiogroup', 'aria-label': 'Edge TTS voices' })
    const voiceStatus = h('p', { class: 'field-hint', role: 'status', 'aria-live': 'polite' })
    const selectedVoice = h('p', { class: 'voice-selected', 'aria-live': 'polite' })
    let voices: EdgeVoice[] = []

    function paintSelectedVoice(): void {
      replace(selectedVoice, icon('check', 14), h('span', null, 'Selected: '), h('strong', null, edge.voice_label || edge.voice), edge.voice_label ? h('code', null, edge.voice) : null)
    }

    function paintVoices(): void {
      const terms = voiceSearch.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
      const language = languageSelect.value
      const gender = genderSelect.value
      const matches = voices.filter((voice) => {
        if (language && voice.locale_name !== language) return false
        if (gender && voice.gender !== gender) return false
        const haystack = `${voice.name} ${voice.id} ${voice.locale} ${voice.locale_name} ${voice.personalities.join(' ')}`.toLowerCase()
        return terms.every((term) => haystack.includes(term))
      })
      matches.sort((a, b) => Number(b.id === edge.voice) - Number(a.id === edge.voice))
      replace(voiceList, matches.slice(0, VOICE_LIST_LIMIT).map(voiceItem))
      voiceStatus.textContent = !voices.length
        ? ''
        : matches.length === 0
          ? 'No voices match. Try another language or a shorter search.'
          : matches.length > VOICE_LIST_LIMIT
            ? `Showing ${VOICE_LIST_LIMIT} of ${matches.length} voices. Narrow it down with search or language.`
            : `${matches.length} voice${matches.length === 1 ? '' : 's'}.`
    }

    function voiceItem(voice: EdgeVoice): HTMLElement {
      const radio = h('input', { type: 'radio', name: 'edge-voice', value: voice.id, checked: voice.id === edge.voice })
      radio.addEventListener('change', () => {
        edge.voice = voice.id
        edge.voice_label = voice.name
        paintSelectedVoice()
        paintDirty()
      })
      const sample = h(
        'button',
        { type: 'button', class: 'icon-button voice-play', 'aria-label': `Preview ${voice.name}`, title: 'Preview this voice' },
        icon('play', 16),
      )
      sample.addEventListener('click', () => {
        edge.voice = voice.id
        edge.voice_label = voice.name
        radio.checked = true
        paintSelectedVoice()
        paintDirty()
        void runPreview()
      })
      return h(
        'li',
        { class: 'voice-item' },
        h('label', { class: 'voice-option' }, radio, h('span', { class: 'voice-text' }, h('span', { class: 'voice-name' }, voice.name), h('span', { class: 'voice-meta' }, edgeVoiceMeta(voice)))),
        sample,
      )
    }

    async function fetchVoices(refresh = false): Promise<void> {
      refreshVoices.disabled = true
      replace(voiceStatus, spinner('Loading voices'), ' Loading voices from the Edge speech service…')
      try {
        voices = await loadEdgeVoices(refresh)
        const languages = [...new Set(voices.map((v) => v.locale_name))].sort((a, b) => a.localeCompare(b))
        const selectedLanguage = languageSelect.value
        replace(languageSelect, h('option', { value: '' }, 'All languages'), languages.map((name) => h('option', { value: name, selected: name === selectedLanguage }, name)))
        const known = voices.find((v) => v.id === edge.voice)
        if (known && !edge.voice_label) edge.voice_label = known.name
        paintSelectedVoice()
        paintVoices()
      } catch (error) {
        replace(
          voiceStatus,
          h('span', { class: 'form-error' }, errorMessage(error), ' The current voice still works; the list needs internet access.'),
          ' ',
          h('button', { type: 'button', class: 'button button-small', onclick: () => void fetchVoices(true) }, icon('retry', 14), 'Try again'),
        )
      }
      refreshVoices.disabled = false
    }

    voiceSearch.addEventListener('input', paintVoices)
    languageSelect.addEventListener('change', paintVoices)
    genderSelect.addEventListener('change', paintVoices)
    refreshVoices.addEventListener('click', () => void fetchVoices(true))

    // Edge controls -----------------------------------------------------------------------
    const controlDefs: { key: 'rate' | 'pitch' | 'volume'; label: string; unit: string; hint: string }[] = [
      { key: 'rate', label: 'Speed', unit: '%', hint: 'Speaking rate relative to the voice’s normal pace.' },
      { key: 'pitch', label: 'Pitch', unit: 'Hz', hint: 'Shifts the voice higher or lower.' },
      { key: 'volume', label: 'Volume', unit: '%', hint: 'Final narration is loudness-normalised either way.' },
    ]
    const controlInputs = new Map<string, { input: HTMLInputElement; output: HTMLOutputElement }>()
    const controls = h(
      'div',
      { class: 'slider-grid slider-grid-3' },
      controlDefs.map((def) => {
        const [min, max] = current.limits[def.key]
        const id = `edge-${def.key}`
        const input = h('input', { type: 'range', id, min, max, step: def.key === 'pitch' ? 1 : 5, value: edge[def.key], 'aria-describedby': `${id}-hint` })
        const output = h('output', { for: id, class: 'range-value' }, signed(edge[def.key], def.unit))
        input.addEventListener('input', () => {
          edge[def.key] = Number(input.value)
          output.textContent = signed(edge[def.key], def.unit)
          paintDirty()
        })
        controlInputs.set(def.key, { input, output })
        return h(
          'div',
          { class: 'field' },
          h('label', { for: id }, def.label),
          h('div', { class: 'range-row' }, input, output),
          h('p', { class: 'field-hint', id: `${id}-hint` }, def.hint),
        )
      }),
    )
    const resetControls = h('button', { type: 'button', class: 'button button-small button-ghost' }, icon('retry', 14), 'Reset speed, pitch and volume')
    resetControls.addEventListener('click', () => {
      for (const def of controlDefs) {
        edge[def.key] = 0
        const pair = controlInputs.get(def.key)
        if (pair) {
          pair.input.value = '0'
          pair.output.textContent = signed(0, def.unit)
        }
      }
      paintDirty()
    })

    edgeSection.append(
      h('h3', { id: 'edge-voice-title', class: 'subsection-title' }, icon('voice', 16), 'Voice'),
      selectedVoice,
      h('div', { class: 'voice-filters', role: 'search' }, h('label', { for: 'edge-voice-search', class: 'sr-only' }, 'Search voices'), voiceSearch, languageSelect, genderSelect, refreshVoices),
      voiceList,
      voiceStatus,
      h('h3', { class: 'subsection-title' }, icon('sliders', 16), 'Delivery'),
      controls,
      h('div', { class: 'form-actions form-actions-start' }, resetControls),
    )

    // ElevenLabs --------------------------------------------------------------------------
    const elevenSection = h('section', { class: 'narration-section' })
    function paintEleven(): void {
      if (!elevenlabs) {
        replace(elevenSection, h('p', { class: 'muted' }, 'ElevenLabs is unavailable in this build.'))
        return
      }
      replace(
        elevenSection,
        credentialCard(elevenlabs, {
          encryptionConfigured,
          onChange: async (next) => {
            elevenlabs = next
            elevenConfigured = next.configured
            await refreshApp().catch(() => {})
            current = await narration.settings().catch(() => current)
            paintProviders()
            paintEleven()
            paintReadiness()
          },
        }),
        elevenLabsPanel(elevenConfigured, { onSaved: () => void narration.settings().then((s) => { current = s; paintReadiness() }).catch(() => {}) }),
      )
    }

    // Preview -----------------------------------------------------------------------------
    const max = current.limits.preview_max_chars
    const previewText = h('textarea', { id: 'narration-preview-text', rows: 2, maxlength: max }, SAMPLE_TEXT)
    const previewCount = h('span', { class: 'muted' })
    const previewButton = h('button', { type: 'button', class: 'button button-secondary button-small' }, icon('play', 14), 'Preview narration')
    const previewPlayer = h('audio', { controls: true, hidden: true, class: 'voice-preview-audio' })
    const previewStatus = h('p', { class: 'provider-result', role: 'status', 'aria-live': 'polite' })
    const previewNote = h('p', { class: 'field-hint' })
    let watcher: JobWatcher | null = null
    previewText.addEventListener('input', () => {
      previewCount.textContent = `${previewText.value.length}/${max}`
    })
    previewCount.textContent = `${previewText.value.length}/${max}`

    function previewDone(job: Job): void {
      watcher = null
      previewButton.disabled = false
      if (job.status === 'succeeded') {
        const result = job.result as unknown as NarrationPreviewResult | null
        const preview = result?.preview
        if (!preview) {
          replace(previewStatus, h('span', { class: 'form-error' }, 'The preview finished without audio. Try again.'))
          return
        }
        previewPlayer.src = mediaUrl(preview.url)
        previewPlayer.hidden = false
        previewStatus.className = 'provider-result ok'
        replace(
          previewStatus,
          icon('checkCircle', 14),
          h('span', null, `Recorded with ${preview.provider_label} · ${preview.voice}${preview.duration_seconds ? ` · ${preview.duration_seconds.toFixed(1)} s` : ''}`),
        )
        void previewPlayer.play().catch(() => {})
        return
      }
      previewStatus.className = 'provider-result fail'
      replace(
        previewStatus,
        icon('error', 14),
        h('span', null, job.error?.message ?? (job.status === 'cancelled' ? 'Preview cancelled.' : 'The preview failed.')),
        ' ',
        h('button', { type: 'button', class: 'button button-small', onclick: () => void runPreview() }, icon('retry', 14), 'Retry'),
      )
    }

    async function runPreview(): Promise<void> {
      const text = previewText.value.trim()
      if (!text) {
        previewStatus.className = 'provider-result fail'
        replace(previewStatus, icon('error', 14), h('span', null, 'Enter a sentence to preview.'))
        previewText.focus()
        return
      }
      watcher?.stop()
      previewButton.disabled = true
      previewStatus.className = 'provider-result'
      replace(previewStatus, spinner('Recording'), h('span', null, provider === 'edge' ? ' Recording with Edge TTS (online)…' : ' Recording with ElevenLabs…'))
      const config: NarrationPreviewConfig =
        provider === 'edge' ? { provider, voice: edge.voice, voice_label: edge.voice_label, rate: edge.rate, pitch: edge.pitch, volume: edge.volume } : { provider }
      try {
        const job = await narration.preview(text, config)
        if (isTerminal(job.status)) {
          previewDone(job)
        } else {
          watcher = watchJob(job.id, {
            onUpdate: () => {},
            onDone: previewDone,
            onError: (error) => {
              previewButton.disabled = false
              replace(previewStatus, h('span', { class: 'form-error' }, errorMessage(error)))
            },
          })
        }
      } catch (error) {
        previewButton.disabled = false
        previewStatus.className = 'provider-result fail'
        replace(previewStatus, icon('error', 14), h('span', null, errorMessage(error)))
      }
    }
    previewButton.addEventListener('click', () => void runPreview())

    const previewSection = h(
      'section',
      { class: 'narration-section narration-preview', 'aria-labelledby': 'narration-preview-title' },
      h('h3', { id: 'narration-preview-title', class: 'subsection-title' }, icon('volume', 16), 'Preview'),
      h('label', { for: 'narration-preview-text', class: 'sr-only' }, 'Preview text'),
      previewText,
      h('div', { class: 'preview-row' }, previewButton, previewCount),
      previewNote,
      previewStatus,
      previewPlayer,
    )

    // Readiness, save -----------------------------------------------------------------------
    const readinessLine = h('div', { class: 'readiness-line', role: 'status', 'aria-live': 'polite' })
    const dirtyNote = h('span', { class: 'dirty-note', hidden: true }, 'Unsaved changes')
    const saveButton = h('button', { type: 'submit', class: 'button button-primary' }, options.submitLabel ?? 'Save narration settings')
    const formError = h('p', { class: 'form-error', role: 'alert', hidden: true })

    function isDirty(): boolean {
      const s = current
      return (
        provider !== s.provider ||
        edge.voice !== s.edge.voice ||
        edge.rate !== s.edge.rate ||
        edge.pitch !== s.edge.pitch ||
        edge.volume !== s.edge.volume
      )
    }

    function paintDirty(): void {
      dirtyNote.hidden = !isDirty()
    }

    function paintReadiness(): void {
      const r = current.readiness
      const pendingEleven = provider === 'elevenlabs' && !elevenConfigured
      const ready = isDirty() ? !pendingEleven : r.ready
      readinessLine.className = `readiness-line ${ready ? 'ok' : 'warn'}`
      replace(
        readinessLine,
        icon(ready ? 'checkCircle' : 'alert', 16),
        h(
          'span',
          null,
          isDirty()
            ? pendingEleven
              ? 'ElevenLabs has no key yet. Narrated shorts will stop with a clear error until you add one or switch back to Edge TTS.'
              : 'Save to make this the default for new narrations.'
            : r.ready
              ? `Default narration: ${narrationSummary(r.provider, r.voice_label, r.voice)}.`
              : (r.problem ?? 'Narration is not ready.'),
        ),
      )
    }

    function paintProviders(): void {
      replace(providerGroup, providerOption('edge'), providerOption('elevenlabs'))
    }

    function paint(): void {
      for (const card of providerGroup.querySelectorAll('.choice-card')) {
        card.classList.toggle('is-selected', card.classList.contains(`choice-${provider}`))
      }
      replace(disclosure, icon(provider === 'edge' ? 'globe' : 'info', 16), h('p', null, info(provider)?.disclosure ?? ''))
      disclosure.className = `notice ${provider === 'edge' ? 'notice-info' : 'notice-warn'} narration-disclosure`
      edgeSection.hidden = provider !== 'edge'
      elevenSection.hidden = provider !== 'elevenlabs'
      previewNote.textContent =
        provider === 'edge'
          ? 'Free. The text is sent to Microsoft’s online speech service; nothing runs until you click.'
          : 'Uses ElevenLabs credits for every character, with the voice saved above. Nothing runs until you click.'
      if (provider === 'edge' && !voices.length) void fetchVoices()
      paintDirty()
      paintReadiness()
    }

    const form = h(
      'form',
      { class: 'narration-form' },
      h('fieldset', null, h('legend', null, 'Provider'), providerGroup, disclosure),
      edgeSection,
      elevenSection,
      previewSection,
      readinessLine,
      formError,
      h('div', { class: 'form-actions' }, dirtyNote, saveButton),
    )
    form.addEventListener('input', paintDirty)
    form.addEventListener('submit', async (event) => {
      event.preventDefault()
      formError.hidden = true
      saveButton.disabled = true
      replace(saveButton, spinner('Saving'), ' Saving…')
      try {
        current = await narration.save(provider, edge)
        Object.assign(edge, current.edge)
        await refreshApp().catch(() => {})
        toast(`Narration default saved: ${narrationSummary(current.provider, current.readiness.voice_label, current.readiness.voice)}.`, 'success')
        paint()
        await options.onSaved?.(current)
      } catch (error) {
        formError.textContent = errorMessage(error)
        formError.hidden = false
      }
      saveButton.disabled = false
      replace(saveButton, options.submitLabel ?? 'Save narration settings')
    })

    paintProviders()
    paintEleven()
    paintSelectedVoice()
    replace(root, form)
    paint()
  }

  void load()
  return root
}

// --- Pexels -------------------------------------------------------------------------------

export function pexelsPanel(configured: boolean): HTMLElement {
  const root = h('div', { class: 'media-settings media-settings-pexels' })
  replace(root, loadingState('Loading Pexels settings…'))

  async function load(): Promise<void> {
    try {
      render((await media.settings()).pexels)
    } catch (error) {
      replace(root, errorState(error, () => void load()))
    }
  }

  function select<T extends string>(id: string, current: T, choices: [T, string][]): HTMLSelectElement {
    return h('select', { id }, choices.map(([value, label]) => h('option', { value, selected: value === current }, label)))
  }

  function render(saved: PexelsSettings): void {
    const mediaType = select('pexels-type', saved.media_type, [
      ['video', 'Videos'],
      ['photo', 'Photos'],
      ['both', 'Photos and videos'],
    ])
    const orientation = select('pexels-orientation', saved.orientation, [
      ['', 'Any orientation'],
      ['portrait', 'Portrait (vertical shorts)'],
      ['landscape', 'Landscape'],
      ['square', 'Square'],
    ])
    const size = select('pexels-size', saved.size, [
      ['', 'Any size'],
      ['large', 'Large'],
      ['medium', 'Medium'],
      ['small', 'Small'],
    ])
    const saveButton = h('button', { type: 'submit', class: 'button button-primary' }, 'Save Pexels defaults')
    const formError = h('p', { class: 'form-error', role: 'alert', hidden: true })
    const form = h(
      'form',
      { class: 'media-form' },
      configured ? null : h('p', { class: 'muted' }, 'These defaults apply once a Pexels key is saved.'),
      h(
        'div',
        { class: 'field-grid' },
        h('div', { class: 'field' }, h('label', { for: 'pexels-type' }, 'Search for'), mediaType),
        h('div', { class: 'field' }, h('label', { for: 'pexels-orientation' }, 'Orientation'), orientation),
        h('div', { class: 'field' }, h('label', { for: 'pexels-size' }, 'Minimum size'), size),
      ),
      h(
        'p',
        { class: 'field-hint' },
        'Used by stock search and by the visual specialist when it picks scene images. Individual searches can still override them. ',
      ),
      h(
        'div',
        { class: 'notice notice-info' },
        icon('check', 16),
        h(
          'p',
          null,
          'Pexels media is free to use. FrameFusion keeps the photographer’s name and link with every result and shows credits such as “Video by Ana on Pexels”; please keep them when you publish. ',
          externalLink('https://www.pexels.com/license/', 'Pexels license'),
        ),
      ),
      formError,
      h('div', { class: 'form-actions' }, saveButton),
    )
    form.addEventListener('submit', async (event) => {
      event.preventDefault()
      formError.hidden = true
      saveButton.disabled = true
      try {
        await media.savePexels({
          media_type: mediaType.value as PexelsSettings['media_type'],
          orientation: orientation.value as PexelsSettings['orientation'],
          size: size.value as PexelsSettings['size'],
        })
        toast('Pexels defaults saved.', 'success')
      } catch (error) {
        formError.textContent = errorMessage(error)
        formError.hidden = false
      }
      saveButton.disabled = false
    })
    replace(root, form)
  }

  void load()
  return root
}

// --- Imported settings --------------------------------------------------------------------

export function importChoicesPanel(): HTMLElement {
  const root = h('div', { class: 'import-choices' })

  async function load(): Promise<void> {
    replace(root, loadingState('Checking imported settings…'))
    try {
      render((await imports.list()).choices)
    } catch (error) {
      replace(root, errorState(error, () => void load()))
    }
  }

  function render(choices: ImportChoice[]): void {
    if (!choices.length) {
      replace(root, h('p', { class: 'muted' }, 'No imported settings are waiting for a decision.'))
      return
    }
    replace(
      root,
      h(
        'p',
        null,
        'These settings differed between the accounts in your previous FrameFusion database, so nothing was applied. Choose what to keep for each one. API keys are only ever shown masked.',
      ),
      choices.map(choiceForm),
    )
  }

  function choiceForm(choice: ImportChoice): HTMLElement {
    const name = `import-${choice.id}`
    const error = h('p', { class: 'form-error', role: 'alert', hidden: true })
    const apply = h('button', { type: 'submit', class: 'button button-primary button-small' }, 'Apply')
    const option = (value: string, label: string, detail: string, checked = false): HTMLElement =>
      h(
        'label',
        { class: 'choice-option' },
        h('input', { type: 'radio', name, value, checked }),
        h('span', null, h('strong', null, label), h('span', { class: 'muted' }, detail)),
      )
    const form = h(
      'form',
      { class: 'import-choice' },
      h(
        'fieldset',
        null,
        h('legend', null, choice.label),
        option('keep_current', choice.current_summary ? 'Keep current' : 'Leave unset', choice.current_summary || 'Nothing is applied', true),
        choice.candidates.map((candidate) => option(candidate.id, candidate.summary, `From ${candidate.source}`)),
      ),
      error,
      h('div', { class: 'form-actions' }, apply),
    )
    form.addEventListener('submit', async (event) => {
      event.preventDefault()
      const picked = new FormData(form).get(name)
      if (typeof picked !== 'string') return
      apply.disabled = true
      error.hidden = true
      try {
        const next = await imports.resolve(choice.id, picked)
        toast(`${choice.label}: saved your choice.`, 'success')
        await refreshApp().catch(() => {})
        render(next.choices)
      } catch (err) {
        error.textContent = errorMessage(err)
        error.hidden = false
        apply.disabled = false
      }
    })
    return form
  }

  void load()
  return root
}
