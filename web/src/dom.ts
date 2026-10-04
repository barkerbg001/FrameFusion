// Tiny element builder. Text is always set via textContent, so user and model content
// can never inject markup. Only sanitized Markdown (see markdown.ts) uses innerHTML.

import {
  Activity,
  ArrowLeft,
  ArrowRight,
  AudioWaveform,
  Ban,
  Captions,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  Clapperboard,
  Clock,
  Compass,
  createElement,
  Database,
  Download,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  Film,
  FolderOpen,
  Gauge,
  Globe,
  type IconNode,
  Image,
  Images,
  Inbox,
  Info,
  KeyRound,
  Languages,
  Layers,
  Lightbulb,
  LoaderCircle,
  Menu,
  MessageSquare,
  Mic,
  Monitor,
  Moon,
  Music,
  Palette,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Rocket,
  RotateCcw,
  Scissors,
  Search,
  SendHorizontal,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Speech,
  Square,
  Sun,
  Trash2,
  TriangleAlert,
  Upload,
  Users,
  Video,
  Volume2,
  WandSparkles,
  Workflow,
  X,
} from 'lucide'

type Child = Node | string | number | false | null | undefined
type Attrs = Record<string, string | number | boolean | null | undefined | EventListener>

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attrs | null = null,
  ...children: (Child | Child[])[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag)
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue
      if (key.startsWith('on') && typeof value === 'function') {
        el.addEventListener(key.slice(2).toLowerCase(), value)
      } else if (key === 'class') {
        el.className = String(value)
      } else if (value === true) {
        el.setAttribute(key, '')
      } else {
        el.setAttribute(key, String(value))
      }
    }
  }
  append(el, children)
  return el
}

export function append(parent: Node, children: (Child | Child[])[]): void {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue
    parent.appendChild(child instanceof Node ? child : document.createTextNode(String(child)))
  }
}

export function clear(el: Element): void {
  while (el.firstChild) el.removeChild(el.firstChild)
}

export function replace(el: Element, ...children: (Child | Child[])[]): void {
  clear(el)
  append(el, children)
}

// Every icon in the app comes from Lucide, drawn at one stroke width. Import only the
// icons listed here so the bundle stays small.
const ICONS = {
  studio: Clapperboard,
  media: Images,
  agents: Users,
  settings: Settings,
  plus: Plus,
  send: SendHorizontal,
  menu: Menu,
  close: X,
  eye: Eye,
  eyeOff: EyeOff,
  refresh: RefreshCw,
  trash: Trash2,
  download: Download,
  edit: Pencil,
  check: Check,
  checkCircle: CircleCheck,
  alert: TriangleAlert,
  error: CircleAlert,
  info: Info,
  stop: Square,
  retry: RotateCcw,
  film: Film,
  video: Video,
  external: ExternalLink,
  sparkle: Sparkles,
  chevron: ChevronRight,
  chevronDown: ChevronDown,
  back: ArrowLeft,
  next: ArrowRight,
  key: KeyRound,
  sun: Sun,
  moon: Moon,
  monitor: Monitor,
  upload: Upload,
  play: Play,
  pause: Pause,
  voice: Mic,
  speech: Speech,
  image: Image,
  compass: Compass,
  script: FileText,
  scenes: Clapperboard,
  music: Music,
  sound: AudioWaveform,
  edit_cut: Scissors,
  idea: Lightbulb,
  research: Search,
  search: Search,
  globe: Globe,
  language: Languages,
  volume: Volume2,
  gauge: Gauge,
  sliders: SlidersHorizontal,
  captions: Captions,
  inbox: Inbox,
  folder: FolderOpen,
  layers: Layers,
  activity: Activity,
  clock: Clock,
  shield: ShieldCheck,
  palette: Palette,
  database: Database,
  chat: MessageSquare,
  wand: WandSparkles,
  workflow: Workflow,
  rocket: Rocket,
  ban: Ban,
  loader: LoaderCircle,
} satisfies Record<string, IconNode>

export type IconName = keyof typeof ICONS

export const ICON_STROKE = 1.75

export function icon(name: IconName | string, size = 18): SVGSVGElement {
  const node = (ICONS as Record<string, IconNode>)[name] ?? ICONS.sparkle
  const svg = createElement(node, {
    width: size,
    height: size,
    'stroke-width': ICON_STROKE,
    'aria-hidden': 'true',
    focusable: 'false',
    class: 'icon',
  }) as SVGSVGElement
  return svg
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  const seconds = Math.round((Date.now() - date.getTime()) / 1000)
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  if (Math.abs(seconds) < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (Math.abs(minutes) < 60) return rtf.format(-minutes, 'minute')
  const hours = Math.round(minutes / 60)
  if (Math.abs(hours) < 24) return rtf.format(-hours, 'hour')
  const days = Math.round(hours / 24)
  if (Math.abs(days) < 7) return rtf.format(-days, 'day')
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds && seconds !== 0) return ''
  const total = Math.round(seconds)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function spinner(label = 'Loading'): HTMLElement {
  return h('span', { class: 'spinner', role: 'status' }, h('span', { class: 'sr-only' }, label))
}

export function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
