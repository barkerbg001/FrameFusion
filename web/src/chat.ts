import {
  checkApiConnection,
  resolveMediaUrl,
  sendChat,
  type StoredChatMessage,
} from './api/client.ts'
import { renderMarkdown } from './markdown.ts'
import './chat.css'

const SUGGESTIONS = [
  { label: 'Research', prompt: 'Research a topic for a short video with citations' },
  { label: 'Weather', prompt: 'What is the weather in Johannesburg this week?' },
  { label: 'Pokemon', prompt: 'Tell me about Pikachu with verified facts' },
  { label: 'Create video', prompt: 'Create a narrated short video about Pikachu with interesting facts' },
] as const

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function getGreeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

function renderMessageBody(message: StoredChatMessage): string {
  if (message.role === 'assistant') {
    return `<div class="chat-md">${renderMarkdown(message.content)}</div>`
  }
  return `<p class="chat-plain">${escapeHtml(message.content)}</p>`
}

function renderAttachments(message: StoredChatMessage): string {
  if (!message.attachments?.length) {
    return ''
  }

  return `
    <div class="chat-attachments">
      ${message.attachments
        .map((attachment) => {
          const src = resolveMediaUrl(attachment.url)
          const duration =
            attachment.duration_seconds != null
              ? `<span class="attachment-meta">${Math.round(attachment.duration_seconds)}s</span>`
              : ''
          return `
            <div class="chat-attachment">
              <div class="attachment-header">
                <span class="attachment-name">${escapeHtml(attachment.filename)}</span>
                ${duration}
              </div>
              <video class="attachment-video" controls playsinline preload="metadata" src="${escapeHtml(src)}"></video>
              <a class="attachment-download" href="${escapeHtml(src)}" download="${escapeHtml(attachment.filename)}">Download MP4</a>
            </div>
          `
        })
        .join('')}
    </div>
  `
}

function renderMessages(log: HTMLElement, messages: StoredChatMessage[]): void {
  log.innerHTML = messages
    .map(
      (message) => `
        <article class="chat-message ${message.role}">
          ${renderMessageBody(message)}
          ${renderAttachments(message)}
        </article>
      `,
    )
    .join('')
  log.scrollTop = log.scrollHeight
}

function showThinkingIndicator(log: HTMLElement): void {
  removeThinkingIndicator(log)
  const indicator = document.createElement('article')
  indicator.className = 'chat-message assistant chat-thinking'
  indicator.setAttribute('aria-live', 'polite')
  indicator.setAttribute('aria-busy', 'true')
  indicator.innerHTML = `
    <div class="thinking-indicator">
      <span class="thinking-label">Frammy is thinking</span>
      <span class="thinking-dots" aria-hidden="true">
        <span></span><span></span><span></span>
      </span>
    </div>
  `
  log.appendChild(indicator)
  log.scrollTop = log.scrollHeight
}

function removeThinkingIndicator(log: HTMLElement): void {
  log.querySelector('.chat-thinking')?.remove()
}

export async function setupAgentChat(root: HTMLElement): Promise<void> {
  root.innerHTML = `
    <div class="chat-app">
      <aside class="chat-sidebar">
        <div class="sidebar-top">
          <div class="sidebar-brand">
            <span class="sidebar-logo" aria-hidden="true">F</span>
            <span class="sidebar-title">Frammy</span>
          </div>
          <button id="chat-new" type="button" class="sidebar-new">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.75" d="M12 5v14M5 12h14"/></svg>
            New chat
          </button>
        </div>

        <nav class="sidebar-nav" aria-label="Chat navigation">
          <a class="sidebar-link active" href="#" aria-current="page">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.75" d="M4 6h16M4 12h10M4 18h14"/></svg>
            Chats
          </a>
          <a class="sidebar-link" href="#">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.75" d="M3 7h18v10H3V7zm11-4 4 4 4-4v4h-8V3z"/></svg>
            Projects
          </a>
          <a class="sidebar-link" href="#">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.75" d="M12 3l2.2 6.8H21l-5.5 4 2.2 6.8L12 16.6 6.3 20.6l2.2-6.8L3 9.8h6.8L12 3z"/></svg>
            Tools
          </a>
        </nav>

        <div class="sidebar-section">
          <p class="sidebar-label">Recents</p>
          <p class="sidebar-empty" id="sidebar-recent">No conversations yet</p>
        </div>

        <div class="sidebar-footer">
          <div class="sidebar-user">
            <span class="sidebar-avatar" aria-hidden="true">U</span>
            <div>
              <p class="sidebar-user-name">You</p>
              <p class="sidebar-user-plan" id="chat-status">Checking API…</p>
            </div>
          </div>
        </div>
      </aside>

      <main class="chat-main">
        <div class="chat-greeting" id="chat-greeting">
          <span class="greeting-icon" aria-hidden="true">✦</span>
          <h1>${getGreeting()}</h1>
          <p class="greeting-subtitle">I'm Frammy — your short-form video director.</p>
        </div>

        <div id="chat-log" class="chat-log" aria-live="polite"></div>

        <div class="chat-composer-wrap">
          <form id="chat-form" class="chat-form">
            <textarea
              id="chat-input"
              rows="1"
              maxlength="8000"
              placeholder="Ask Frammy anything…"
              autocomplete="off"
            ></textarea>
            <div class="chat-form-actions">
              <button id="chat-send" type="submit" class="chat-send" aria-label="Send message">
                <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                  <path fill="currentColor" d="M3.4 20.6 21 12 3.4 3.4l2.8 7.2L17 12l-10.8 1.4z"/>
                </svg>
              </button>
            </div>
          </form>
          <div class="chat-suggestions" id="chat-suggestions">
            ${SUGGESTIONS.map(
              (item) =>
                `<button type="button" class="chat-pill" data-prompt="${escapeHtml(item.prompt)}">${escapeHtml(item.label)}</button>`,
            ).join('')}
          </div>
        </div>
      </main>
    </div>
  `

  const app = root.querySelector<HTMLElement>('.chat-app')!
  const statusEl = root.querySelector<HTMLParagraphElement>('#chat-status')!
  const greetingEl = root.querySelector<HTMLElement>('#chat-greeting')!
  const log = root.querySelector<HTMLElement>('#chat-log')!
  const form = root.querySelector<HTMLFormElement>('#chat-form')!
  const messageInput = root.querySelector<HTMLTextAreaElement>('#chat-input')!
  const sendButton = root.querySelector<HTMLButtonElement>('#chat-send')!
  const suggestionsEl = root.querySelector<HTMLElement>('#chat-suggestions')!
  const recentEl = root.querySelector<HTMLParagraphElement>('#sidebar-recent')!
  const newChatButton = root.querySelector<HTMLButtonElement>('#chat-new')!

  const messages: StoredChatMessage[] = []
  let isSending = false
  let apiOnline = false

  function hasUserMessages(): boolean {
    return messages.some((message) => message.role === 'user')
  }

  function updateLayout(): void {
    const started = hasUserMessages() || isSending
    app.classList.toggle('chat-started', started)
    greetingEl.hidden = started
    suggestionsEl.hidden = started
    if (hasUserMessages()) {
      renderMessages(log, messages)
    } else if (!isSending) {
      log.innerHTML = ''
    }
  }

  function resizeInput(): void {
    messageInput.style.height = 'auto'
    messageInput.style.height = `${Math.min(messageInput.scrollHeight, 200)}px`
  }

  messageInput.addEventListener('input', resizeInput)
  messageInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      form.requestSubmit()
    }
  })

  apiOnline = await checkApiConnection()
  if (apiOnline) {
    statusEl.textContent = 'Frammy is ready'
  } else {
    statusEl.textContent = 'API offline'
    messageInput.placeholder = 'Start the API to chat…'
  }

  function setSending(sending: boolean): void {
    isSending = sending
    sendButton.disabled = sending || !apiOnline
    messageInput.disabled = sending || !apiOnline
    app.classList.toggle('chat-loading', sending)
    updateLayout()

    if (sending) {
      showThinkingIndicator(log)
      statusEl.textContent = 'Frammy is thinking…'
    } else {
      removeThinkingIndicator(log)
      if (apiOnline) {
        statusEl.textContent = 'Frammy is ready'
      }
    }
  }

  async function submitMessage(content: string): Promise<void> {
    if (!content || isSending || !apiOnline) {
      return
    }

    messages.push({ role: 'user', content })
    updateLayout()
    messageInput.value = ''
    resizeInput()
    setSending(true)

    const preview = content.length > 36 ? `${content.slice(0, 36)}…` : content
    recentEl.textContent = preview

    try {
      const reply = await sendChat(messages)
      messages.push(reply)
      renderMessages(log, messages)
    } catch (error) {
      const detail =
        error instanceof Error ? error.message : 'Something went wrong.'
      messages.push({
        role: 'assistant',
        content: `Sorry, I couldn't respond:\n\n\`${detail}\``,
      })
      renderMessages(log, messages)
    } finally {
      setSending(false)
      messageInput.focus()
    }
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault()
    await submitMessage(messageInput.value.trim())
  })

  suggestionsEl.addEventListener('click', (event) => {
    const target = (event.target as HTMLElement).closest<HTMLButtonElement>(
      '[data-prompt]',
    )
    if (!target) {
      return
    }
    void submitMessage(target.dataset.prompt ?? '')
  })

  newChatButton.addEventListener('click', () => {
    messages.length = 0
    recentEl.textContent = 'No conversations yet'
    updateLayout()
    messageInput.focus()
  })

  root.querySelectorAll<HTMLAnchorElement>('.sidebar-link').forEach((link) => {
    link.addEventListener('click', (event) => event.preventDefault())
  })

  updateLayout()
}
