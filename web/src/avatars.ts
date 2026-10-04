import framey from './assets/agents/framey-avatar.webp'
import frameyPortrait from './assets/agents/framey-portrait.webp'
import reel from './assets/agents/reel-avatar.webp'
import reelPortrait from './assets/agents/reel-portrait.webp'
import type { PersonalityId } from './api.ts'
import { h } from './dom.ts'

export type AvatarState = 'idle' | 'setup' | 'working' | 'success' | 'error'

/** Colour family from tokens.css: framey is red, reel is blue. */
export type Tone = 'framey' | 'reel'

export interface PersonalityLook {
  id: PersonalityId
  name: string
  tagline: string
  summary: string
  tone: Tone
  avatar: string
  portrait: string
}

/**
 * Both personalities are the same orchestrator with the same tools and permissions;
 * only the voice and the avatar differ.
 */
export const PERSONALITIES: Record<PersonalityId, PersonalityLook> = {
  director: {
    id: 'director',
    name: 'Director',
    tagline: 'Decisive, structured, concise',
    summary: 'Makes clear calls, states the plan in numbered steps and keeps replies short.',
    tone: 'reel',
    avatar: reel,
    portrait: reelPortrait,
  },
  creative_partner: {
    id: 'creative_partner',
    name: 'Creative Partner',
    tagline: 'Imaginative, conversational',
    summary: 'Thinks out loud with you, offers a couple of creative angles and keeps the tone warm.',
    tone: 'framey',
    avatar: framey,
    portrait: frameyPortrait,
  },
}

export const PERSONALITY_IDS = Object.keys(PERSONALITIES) as PersonalityId[]

export function personality(id: string | null | undefined): PersonalityLook {
  return PERSONALITIES[(id ?? '') as PersonalityId] ?? PERSONALITIES.director
}

const STATE_LABEL: Record<AvatarState, string> = {
  idle: 'idle',
  setup: 'needs setup',
  working: 'working',
  success: 'finished',
  error: 'needs attention',
}

export function avatar(
  id: PersonalityId | string | null | undefined,
  options: { size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'; state?: AvatarState; portrait?: boolean } = {},
): HTMLElement {
  const info = personality(id)
  const size = options.size ?? 'md'
  const state = options.state ?? 'idle'
  return h(
    'span',
    {
      class: `avatar avatar-${size} avatar-${info.tone}`,
      'data-state': state,
      'data-personality': info.id,
      role: 'img',
      'aria-label': `${info.name}, ${STATE_LABEL[state]}`,
    },
    h('img', {
      src: options.portrait ? info.portrait : info.avatar,
      alt: '',
      width: 96,
      height: 96,
      decoding: 'async',
      draggable: 'false',
    }),
    h('span', { class: 'avatar-status', 'aria-hidden': 'true' }),
  )
}

export function setAvatarState(el: HTMLElement, state: AvatarState): void {
  el.dataset.state = state
  el.setAttribute('aria-label', `${personality(el.dataset.personality).name}, ${STATE_LABEL[state]}`)
}
