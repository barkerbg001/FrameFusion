const API_URL = import.meta.env.VITE_API_URL ?? ''

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${API_URL}${path}`, init)

  if (!response.ok) {
    const detail = await response.text()
    throw new ApiError(detail || response.statusText, response.status)
  }

  return response
}

export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  role: ChatRole
  content: string
}

export interface ChatAttachment {
  type: 'video' | 'audio'
  url: string
  filename: string
  duration_seconds?: number | null
}

export interface StoredChatMessage extends ChatMessage {
  attachments?: ChatAttachment[]
}

export interface ChatResponse {
  message: ChatMessage
  attachments?: ChatAttachment[]
}

export interface ServerVideoItem {
  url: string
  filename: string
  created_at: number
}

export async function checkApiConnection(): Promise<boolean> {
  try {
    await apiFetch('/api/chat/health')
    return true
  } catch {
    return false
  }
}

export function resolveMediaUrl(path: string): string {
  return `${API_URL}${path}`
}

export async function listGeneratedVideos(): Promise<ServerVideoItem[]> {
  const response = await apiFetch('/api/chat/videos')
  return (await response.json()) as ServerVideoItem[]
}

export async function sendChat(
  messages: ChatMessage[],
): Promise<StoredChatMessage> {
  const response = await apiFetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  })
  const data = (await response.json()) as ChatResponse
  return {
    ...data.message,
    attachments: data.attachments?.length ? data.attachments : undefined,
  }
}
