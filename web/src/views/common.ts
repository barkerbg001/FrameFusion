import {
  ApiError,
  type JobError,
  type NarrationProvider,
  type ProjectNarration,
  type Readiness,
} from '../api.ts'
import { avatar } from '../avatars.ts'
import { h, icon, spinner } from '../dom.ts'
import { state } from '../state.ts'

export function pageHeader(
  title: string,
  description?: string,
  actions: Node[] = [],
): HTMLElement {
  return h(
    'header',
    { class: 'page-header' },
    h(
      'div',
      { class: 'page-heading' },
      h('h1', { tabindex: '-1', 'data-autofocus': true }, title),
      description ? h('p', { class: 'page-description' }, description) : null,
    ),
    actions.length ? h('div', { class: 'page-actions' }, actions) : null,
  )
}

export function loadingState(label = 'Loading…'): HTMLElement {
  return h('div', { class: 'state state-loading' }, spinner(label), h('p', null, label))
}

export function illustration(src: string, width = 800, height = 600): HTMLElement {
  return h('img', { class: 'illustration', src, alt: '', width, height, decoding: 'async', loading: 'lazy' })
}

export function emptyState(
  title: string,
  body: string,
  action?: Node,
  art?: Node,
): HTMLElement {
  return h(
    'div',
    { class: 'state state-empty' },
    art ?? null,
    h('h2', null, title),
    h('p', null, body),
    action ?? null,
  )
}

export function errorState(error: unknown, retry?: () => void): HTMLElement {
  const message = errorMessage(error)
  return h(
    'div',
    { class: 'state state-error', role: 'alert' },
    h('span', { class: 'state-icon' }, icon('alert', 22)),
    h('h2', null, 'Something went wrong'),
    h('p', null, message),
    retry
      ? h(
          'button',
          { type: 'button', class: 'button', onclick: retry },
          icon('retry', 16),
          'Try again',
        )
      : null,
  )
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const errors = error.payload.errors
    if (error.code === 'validation_error' && Array.isArray(errors) && errors.length) {
      return errors
        .map((item) => {
          const entry = item as { field?: string; message?: string }
          return entry.field ? `${entry.field}: ${entry.message}` : String(entry.message)
        })
        .join(' ')
    }
    return error.message
  }
  if (error instanceof Error) return error.message
  return 'Unexpected error.'
}

// Next-step guidance for a failed job or provider call, by normalized error kind.
export function errorGuidance(error: JobError | null | undefined): {
  hint: string
  settings: boolean
  retry: boolean
} {
  const kind = error?.kind ?? ''
  switch (kind) {
    case 'narration_failed':
      return {
        hint: error?.can_retry_narration
          ? 'The script and visuals were kept. Retry just the narration, or change the voice or provider first.'
          : 'Check the narration voice and provider, then retry.',
        settings: true,
        retry: true,
      }
    case 'not_configured':
      if (error?.service) {
        const label = error.service === 'elevenlabs' ? 'ElevenLabs' : 'Pexels'
        return {
          hint:
            error.service === 'elevenlabs'
              ? 'Add an ElevenLabs key in Settings → Narration, or switch narration to free Edge TTS, then retry.'
              : `Add a ${label} key in Settings → Stock media, then retry.`,
          settings: true,
          retry: true,
        }
      }
      return { hint: 'Finish AI setup in Settings, then retry.', settings: true, retry: true }
    case 'encryption_unavailable':
      return {
        hint: 'The server administrator needs to set FRAMEFUSION_ENCRYPTION_KEY.',
        settings: false,
        retry: false,
      }
    case 'invalid_credentials':
    case 'permission_denied':
      return { hint: 'Update or re-test the API key in Settings.', settings: true, retry: true }
    case 'quota_exceeded':
      return {
        hint: 'Add credit with the provider or switch provider in Settings.',
        settings: true,
        retry: true,
      }
    case 'model_unavailable':
      return { hint: 'Choose a different model in Settings.', settings: true, retry: true }
    case 'rate_limited':
      return { hint: 'The provider is rate limiting requests. Wait a moment, then retry.', settings: false, retry: true }
    case 'timeout':
    case 'network':
    case 'provider_error':
      return { hint: 'This is usually temporary. Retry in a moment.', settings: false, retry: true }
    case 'no_images':
      return {
        hint: 'Search for images yourself in the Scenes tab, or reword the brief, then re-run. Finished stages are reused.',
        settings: false,
        retry: true,
      }
    case 'qc_failed':
      return { hint: 'Re-run the render; earlier stages are reused.', settings: false, retry: true }
    case 'invalid_artifact':
      return { hint: 'The specialist’s output did not pass its checks. Retry, or try a different model.', settings: false, retry: true }
    case 'stage_failed':
      return { hint: 'Retry resumes from the failed stage; finished stages are reused.', settings: false, retry: true }
    case 'cancelled':
      return { hint: 'You cancelled this run. Retry resumes where it stopped.', settings: false, retry: true }
    case 'interrupted':
      return { hint: 'The server restarted during this run.', settings: false, retry: true }
    default:
      return { hint: '', settings: false, retry: true }
  }
}

export function setupNotice(readiness: Record<string, Readiness> | null, routes: string[]): HTMLElement | null {
  if (!readiness) return null
  const blocked = routes
    .map((route) => readiness[route])
    .filter((r): r is Readiness => Boolean(r && !r.ready))
  if (!blocked.length) return null
  return h(
    'div',
    { class: 'notice notice-warn', role: 'status' },
    h('div', { class: 'notice-avatars' }, avatar(state.app?.personality, { size: 'sm', state: 'setup' })),
    h(
      'div',
      { class: 'notice-body' },
      h(
        'strong',
        null,
        blocked.length === 1
          ? `The orchestrator needs an AI model for “${blocked[0]!.name}”`
          : 'The orchestrator and its specialists need an AI provider',
      ),
      h('p', null, blocked.map((r) => r.problem).join(' ')),
    ),
    h('a', { class: 'button button-primary', href: '#/settings' }, icon('key', 16), 'Open AI settings'),
  )
}

export function settingsHref(error: JobError | null | undefined): string {
  if (error?.settings_path?.startsWith('#/settings')) return error.settings_path
  if (error?.kind === 'narration_failed' || error?.service === 'elevenlabs') return '#/settings/narration'
  if (error?.service === 'pexels') return '#/settings/media'
  return '#/settings'
}

// The narration a production in this project will use: the project override, else the default.
export function effectiveNarration(override: ProjectNarration | null | undefined): {
  provider: NarrationProvider
  voice: string
  voiceLabel: string
  overridden: boolean
  ready: boolean
  problem: string | null
} | null {
  const base = state.app?.narration
  if (!base) return null
  if (!override?.provider) {
    return { provider: base.provider, voice: base.voice, voiceLabel: base.voice_label, overridden: false, ready: base.ready, problem: base.problem }
  }
  const elevenReady = Boolean(state.integrations?.elevenlabs.configured)
  const ready = override.provider === 'edge' || elevenReady
  return {
    provider: override.provider,
    voice: override.voice || (override.provider === base.provider ? base.voice : ''),
    voiceLabel: override.voice_label || (override.provider === base.provider && !override.voice ? base.voice_label : ''),
    overridden: true,
    ready,
    problem: ready ? null : 'This project narrates with ElevenLabs, but no ElevenLabs key is saved.',
  }
}

// What a production will use and what it will be missing without optional integrations.
export function integrationHint(format: string, override?: ProjectNarration | null): HTMLElement | null {
  const integrations = state.integrations
  if (!integrations) return null
  const notes: string[] = []
  let warn = false
  let href = '#/settings/media'
  const voice = effectiveNarration(override)
  if (voice && format !== 'silent') {
    href = '#/settings/narration'
    if (!voice.ready) {
      warn = format === 'narrated'
      notes.push(voice.problem ?? 'Narration is not ready.')
    } else {
      const who = voice.voiceLabel || voice.voice
      notes.push(
        voice.provider === 'edge'
          ? `Narration: free Edge TTS${who ? ` (${who})` : ''}. Needs internet; the script text is sent to Microsoft.`
          : `Narration: ElevenLabs${who ? ` (${who})` : ''}. Uses your ElevenLabs credits.`,
      )
    }
  }
  if (!integrations.pexels.configured) {
    notes.push('Without Pexels, the visual specialist searches Openverse only (Creative Commons images with recorded licences).')
  }
  if (!notes.length) return null
  return h(
    'p',
    { class: `integration-hint${warn ? ' field-warn' : ''}` },
    icon(warn ? 'alert' : 'info', 14),
    h('span', null, notes.join(' '), ' '),
    h('a', { class: 'link', href }, warn ? 'Fix in Settings' : 'Settings'),
  )
}

export function confirmDialog(options: {
  title: string
  body: string
  confirm: string
  danger?: boolean
}): Promise<boolean> {
  return new Promise((resolve) => {
    const dialog = h(
      'dialog',
      { class: 'dialog', 'aria-labelledby': 'dialog-title' },
      h(
        'form',
        { method: 'dialog' },
        h('h2', { id: 'dialog-title', class: options.danger ? 'dialog-title-danger' : null }, options.danger ? icon('alert', 18) : null, options.title),
        h('p', null, options.body),
        h(
          'div',
          { class: 'dialog-actions' },
          h('button', { type: 'submit', value: 'cancel', class: 'button', autofocus: options.danger ? true : null }, 'Cancel'),
          h(
            'button',
            {
              type: 'submit',
              value: 'confirm',
              class: `button ${options.danger ? 'button-danger' : 'button-primary'}`,
            },
            options.danger ? icon('trash', 16) : null,
            options.confirm,
          ),
        ),
      ),
    )
    dialog.addEventListener('close', () => {
      resolve(dialog.returnValue === 'confirm')
      dialog.remove()
    })
    document.body.appendChild(dialog)
    dialog.showModal()
  })
}

export function focusHeading(outlet: HTMLElement): void {
  const heading = outlet.querySelector<HTMLElement>('[data-autofocus]')
  heading?.focus({ preventScroll: true })
}
