import { mediaUrl, studio, type Attachment, type MediaAsset } from '../api.ts'
import emptyMediaArt from '../assets/illustrations/empty-media.webp'
import { formatBytes, formatDuration, h, icon, relativeTime, replace } from '../dom.ts'
import { state } from '../state.ts'
import { toast } from '../toast.ts'
import {
  confirmDialog,
  emptyState,
  errorMessage,
  errorState,
  focusHeading,
  illustration,
  loadingState,
  pageHeader,
} from './common.ts'

type Filter = '' | 'video' | 'audio' | 'image'

export function mediaPlayer(kind: string, url: string, label: string): HTMLElement {
  const src = mediaUrl(url)
  if (kind === 'video') {
    return h('video', { class: 'player', src, controls: true, preload: 'metadata', playsinline: true, 'aria-label': label })
  }
  if (kind === 'audio') {
    return h('audio', { class: 'player player-audio', src, controls: true, preload: 'none', 'aria-label': label })
  }
  return h('img', { class: 'player', src, alt: label, loading: 'lazy' })
}

export function attachmentView(attachment: Attachment): HTMLElement {
  const download = attachment.download_url ?? `${attachment.url}?download=1`
  return h(
    'figure',
    { class: `attachment attachment-${attachment.type}` },
    mediaPlayer(attachment.type, attachment.url, attachment.filename),
    h(
      'figcaption',
      null,
      h('span', { class: 'attachment-name' }, attachment.filename),
      attachment.duration_seconds ? h('span', { class: 'muted' }, formatDuration(attachment.duration_seconds)) : null,
      h(
        'a',
        { class: 'icon-button', href: mediaUrl(download), 'aria-label': `Download ${attachment.filename}`, title: 'Download' },
        icon('download', 16),
      ),
    ),
  )
}

export function mediaThumb(asset: MediaAsset): HTMLElement {
  return h(
    'figure',
    { class: `media-thumb media-${asset.kind}` },
    mediaPlayer(asset.kind, asset.url, asset.display_name),
    h('figcaption', null, h('span', { class: 'attachment-name' }, asset.display_name), h('span', { class: 'muted' }, relativeTime(asset.created_at))),
  )
}

export function mediaView(outlet: HTMLElement): () => void {
  let filter: Filter = ''
  let media: MediaAsset[] = []
  const body = h('div', { class: 'media-body' })

  const filters = h(
    'div',
    { class: 'segmented', role: 'group', 'aria-label': 'Filter media' },
    (
      [
        ['', 'All'],
        ['video', 'Video'],
        ['audio', 'Audio'],
        ['image', 'Images'],
      ] as const
    ).map(([value, label]) =>
      h(
        'button',
        {
          type: 'button',
          class: 'segment',
          'aria-pressed': String(value === filter),
          onclick: (event: Event) => {
            filter = value
            for (const button of filters.querySelectorAll('button')) {
              button.setAttribute('aria-pressed', String(button === event.currentTarget))
            }
            void load()
          },
        },
        label,
      ),
    ),
  )

  replace(
    outlet,
    h(
      'div',
      { class: 'page page-media' },
      pageHeader('Media', 'Every video, audio track and image your projects have produced.', [filters]),
      body,
    ),
  )
  focusHeading(outlet)

  async function load(): Promise<void> {
    replace(body, loadingState('Loading media…'))
    try {
      media = await studio.media(filter || undefined)
      render()
    } catch (error) {
      replace(body, errorState(error, () => void load()))
    }
  }

  function render(): void {
    if (!media.length) {
      replace(
        body,
        emptyState(
          filter ? 'Nothing here yet' : 'No media yet',
          'When a production renders a video, downloads scene images or a tool creates audio, the files appear here. They are stored on this computer.',
          h('a', { class: 'button button-primary', href: '#/' }, icon('studio', 16), 'Go to Studio'),
          filter ? undefined : illustration(emptyMediaArt),
        ),
      )
      return
    }
    replace(body, h('ul', { class: 'media-grid' }, media.map((asset) => h('li', null, mediaCard(asset)))))
  }

  function mediaCard(asset: MediaAsset): HTMLElement {
    const project = asset.project_id ? state.projects.find((p) => p.id === asset.project_id) : undefined
    const meta = [relativeTime(asset.created_at), formatDuration(asset.duration_seconds), formatBytes(asset.size_bytes)].filter(Boolean)
    return h(
      'article',
      { class: 'media-card' },
      mediaPlayer(asset.kind, asset.url, asset.display_name),
      h(
        'div',
        { class: 'media-card-body' },
        h('h2', { class: 'media-title', title: asset.display_name }, asset.display_name),
        h('p', { class: 'muted' }, meta.join(' · ')),
        project
          ? h('a', { class: 'link', href: `#/projects/${project.id}` }, project.title)
          : asset.project_id
            ? h('a', { class: 'link', href: `#/projects/${asset.project_id}` }, 'Open project')
            : null,
      ),
      h(
        'div',
        { class: 'media-card-actions' },
        h(
          'a',
          { class: 'button button-small', href: mediaUrl(asset.download_url) },
          icon('download', 14),
          'Download',
        ),
        h(
          'button',
          {
            type: 'button',
            class: 'icon-button danger',
            'aria-label': `Delete ${asset.display_name}`,
            title: 'Delete',
            onclick: async () => {
              const ok = await confirmDialog({
                title: 'Delete this file?',
                body: `“${asset.display_name}” will be removed from the server. This cannot be undone.`,
                confirm: 'Delete file',
                danger: true,
              })
              if (!ok) return
              try {
                await studio.deleteMedia(asset.id)
                media = media.filter((m) => m.id !== asset.id)
                render()
                toast('File deleted.', 'success')
              } catch (error) {
                toast(errorMessage(error), 'error')
              }
            },
          },
          icon('trash', 16),
        ),
      ),
    )
  }

  void load()
  return () => {}
}
