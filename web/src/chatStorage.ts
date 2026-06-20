import type { StoredChatMessage } from './api/client.ts'

const STORAGE_KEY = 'framefusion:chats'
const MAX_CHATS = 50

export interface SavedChat {
  id: string
  title: string
  updatedAt: number
  messages: StoredChatMessage[]
}

interface ChatStore {
  activeChatId: string
  chats: SavedChat[]
}

function createChatId(): string {
  return crypto.randomUUID()
}

function deriveTitle(messages: StoredChatMessage[]): string {
  const firstUser = messages.find((message) => message.role === 'user')
  if (!firstUser) {
    return 'New chat'
  }
  const trimmed = firstUser.content.trim().replace(/\s+/g, ' ')
  if (!trimmed) {
    return 'New chat'
  }
  return trimmed.length > 40 ? `${trimmed.slice(0, 40)}…` : trimmed
}

function emptyStore(): ChatStore {
  const chat: SavedChat = {
    id: createChatId(),
    title: 'New chat',
    updatedAt: Date.now(),
    messages: [],
  }
  return { activeChatId: chat.id, chats: [chat] }
}

function normalizeStore(raw: unknown): ChatStore {
  if (
    !raw ||
    typeof raw !== 'object' ||
    !('activeChatId' in raw) ||
    !('chats' in raw) ||
    !Array.isArray((raw as ChatStore).chats)
  ) {
    return emptyStore()
  }

  const store = raw as ChatStore
  const chats = store.chats
    .filter(
      (chat): chat is SavedChat =>
        Boolean(chat) &&
        typeof chat.id === 'string' &&
        Array.isArray(chat.messages),
    )
    .map((chat) => ({
      id: chat.id,
      title: typeof chat.title === 'string' ? chat.title : deriveTitle(chat.messages),
      updatedAt: typeof chat.updatedAt === 'number' ? chat.updatedAt : Date.now(),
      messages: chat.messages,
    }))

  if (!chats.length) {
    return emptyStore()
  }

  const activeChatId = chats.some((chat) => chat.id === store.activeChatId)
    ? store.activeChatId
    : chats[0]!.id

  return { activeChatId, chats }
}

export function loadChatStore(): ChatStore {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return emptyStore()
    }
    return normalizeStore(JSON.parse(raw) as unknown)
  } catch {
    return emptyStore()
  }
}

export function saveChatStore(store: ChatStore): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  } catch {
    // Ignore quota or private-mode errors.
  }
}

export function getActiveChat(store: ChatStore): SavedChat {
  return store.chats.find((chat) => chat.id === store.activeChatId) ?? store.chats[0]!
}

export function upsertActiveChat(
  store: ChatStore,
  messages: StoredChatMessage[],
): ChatStore {
  const now = Date.now()
  const title = deriveTitle(messages)
  const chats = store.chats.map((chat) =>
    chat.id === store.activeChatId
      ? { ...chat, messages, title, updatedAt: now }
      : chat,
  )

  const sorted = [...chats].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CHATS)
  const activeStillExists = sorted.some((chat) => chat.id === store.activeChatId)

  return {
    activeChatId: activeStillExists ? store.activeChatId : sorted[0]!.id,
    chats: sorted,
  }
}

export function startNewChat(store: ChatStore): ChatStore {
  const active = getActiveChat(store)
  const withoutEmpty =
    active.messages.length === 0
      ? store.chats.filter((chat) => chat.id !== store.activeChatId)
      : store.chats

  const chat: SavedChat = {
    id: createChatId(),
    title: 'New chat',
    updatedAt: Date.now(),
    messages: [],
  }

  const chats = [chat, ...withoutEmpty].slice(0, MAX_CHATS)
  return { activeChatId: chat.id, chats }
}

export function switchChat(store: ChatStore, chatId: string): ChatStore | null {
  if (!store.chats.some((chat) => chat.id === chatId)) {
    return null
  }
  return { ...store, activeChatId: chatId }
}

export function listRecentChats(store: ChatStore): SavedChat[] {
  return [...store.chats].sort((a, b) => b.updatedAt - a.updatedAt)
}
