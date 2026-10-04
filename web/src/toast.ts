import { h, icon } from './dom.ts'

type Tone = 'info' | 'success' | 'error'

let region: HTMLElement | null = null

function ensureRegion(): HTMLElement {
  if (!region) {
    region = h('div', { class: 'toasts', role: 'region', 'aria-label': 'Notifications' })
    document.body.appendChild(region)
  }
  return region
}

export function toast(message: string, tone: Tone = 'info', timeout = 5000): void {
  const host = ensureRegion()
  const item = h(
    'div',
    { class: `toast toast-${tone}`, role: tone === 'error' ? 'alert' : 'status' },
    icon(tone === 'error' ? 'alert' : tone === 'success' ? 'check' : 'sparkle', 16),
    h('span', null, message),
    h(
      'button',
      {
        type: 'button',
        class: 'icon-button toast-close',
        'aria-label': 'Dismiss notification',
        onclick: () => item.remove(),
      },
      icon('close', 14),
    ),
  )
  host.appendChild(item)
  if (timeout > 0) window.setTimeout(() => item.remove(), timeout)
}
