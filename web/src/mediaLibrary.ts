import type { ChatAttachment } from './api/client.ts'
import type { SavedChat } from './chatStorage.ts'

export interface MediaItem {
  url: string
  filename: string
  duration_seconds?: number | null
  createdAt?: number
  sourceChatTitle?: string
}

export function attachmentToMediaItem(
  attachment: ChatAttachment,
  chat?: SavedChat,
): MediaItem {
  return {
    url: attachment.url,
    filename: attachment.filename,
    duration_seconds: attachment.duration_seconds,
    createdAt: chat?.updatedAt,
    sourceChatTitle: chat?.title,
  }
}

export function collectMediaFromChats(chats: SavedChat[]): MediaItem[] {
  const seen = new Set<string>()
  const items: MediaItem[] = []

  for (const chat of chats) {
    for (const message of chat.messages) {
      for (const attachment of message.attachments ?? []) {
        if (attachment.type !== 'video' || seen.has(attachment.url)) {
          continue
        }
        seen.add(attachment.url)
        items.push(attachmentToMediaItem(attachment, chat))
      }
    }
  }

  return items.sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0))
}

export function mergeMediaItems(local: MediaItem[], server: MediaItem[]): MediaItem[] {
  const merged = new Map<string, MediaItem>()

  for (const item of server) {
    merged.set(item.url, item)
  }

  for (const item of local) {
    const existing = merged.get(item.url)
    merged.set(item.url, {
      ...item,
      ...existing,
      sourceChatTitle: item.sourceChatTitle ?? existing?.sourceChatTitle,
      duration_seconds: item.duration_seconds ?? existing?.duration_seconds,
    })
  }

  return [...merged.values()].sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0))
}
