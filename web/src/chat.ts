import {
  checkApiConnection,
  listGeneratedVideos,
  resolveMediaUrl,
  sendChat,
  type StoredChatMessage,
} from './api/client.ts'
import {
  deleteChat,
  getActiveChat,
  listRecentChats,
  loadChatStore,
  renameChat,
  saveChatStore,
  startNewChat,
  switchChat,
  upsertActiveChat,
  type SavedChat,
} from './chatStorage.ts'
import {
  collectMediaFromChats,
  mergeMediaItems,
  type MediaItem,
} from './mediaLibrary.ts'
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
      <span class="thinking-label">Framey is thinking</span>
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

function renderMediaCard(item: MediaItem): string {
  const src = resolveMediaUrl(item.url)
  const duration =
    item.duration_seconds != null
      ? `${Math.round(item.duration_seconds)}s`
      : ''
  const source = item.sourceChatTitle
    ? `<p class="media-card-source">From chat: ${escapeHtml(item.sourceChatTitle)}</p>`
    : ''

  return `
    <article class="media-card">
      <div class="media-card-header">
        <p class="media-card-title">${escapeHtml(item.filename)}</p>
        ${duration ? `<span class="media-card-meta">${duration}</span>` : ''}
      </div>
      <video controls playsinline preload="metadata" src="${escapeHtml(src)}"></video>
      ${source}
      <a class="media-card-download" href="${escapeHtml(src)}" download="${escapeHtml(item.filename)}">Download MP4</a>
    </article>
  `
}

export async function setupAgentChat(root: HTMLElement): Promise<void> {
  root.innerHTML = `
    <div class="chat-app">
      <aside class="chat-sidebar">
        <div class="sidebar-top">
          <div class="sidebar-brand">
            <span class="sidebar-logo" aria-hidden="true">FF</span>
            <span class="sidebar-title">FrameFusion</span>
          </div>
          <button id="chat-new" type="button" class="sidebar-new">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.75" d="M12 5v14M5 12h14"/></svg>
            New chat
          </button>
        </div>

        <nav class="sidebar-nav" aria-label="Main navigation">
          <a class="sidebar-link active" href="#" data-view="chat" aria-current="page">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.75" d="M4 6h16M4 12h10M4 18h14"/></svg>
            Chats
          </a>
          <a class="sidebar-link" href="#" data-view="media">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.75" d="M4 7h16v10H4V7zm4-4h8v4H8V3z"/></svg>
            Media
          </a>
        </nav>

        <div class="sidebar-section">
          <p class="sidebar-label">Recents</p>
          <div id="sidebar-recents" class="sidebar-recents" role="list"></div>
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
        <div id="chat-view" class="chat-view">
          <div class="chat-greeting" id="chat-greeting">
            <h1>${getGreeting()}</h1>
            <p class="greeting-subtitle">I'm Framey — FrameFusion's AI for short-form video.</p>
          </div>

          <div id="chat-log" class="chat-log" aria-live="polite"></div>

          <div class="chat-composer-wrap">
            <form id="chat-form" class="chat-form">
              <textarea
                id="chat-input"
                rows="1"
                maxlength="8000"
                placeholder="Ask Framey anything…"
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
        </div>

        <section id="media-view" class="media-view" hidden>
          <header class="media-header">
            <h1>Media</h1>
            <p>All videos created by Framey — from your chats and the server.</p>
          </header>
          <div id="media-grid" class="media-grid"></div>
        </section>
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
  const recentsEl = root.querySelector<HTMLElement>('#sidebar-recents')!
  const newChatButton = root.querySelector<HTMLButtonElement>('#chat-new')!
  const chatView = root.querySelector<HTMLElement>('#chat-view')!
  const mediaView = root.querySelector<HTMLElement>('#media-view')!
  const mediaGrid = root.querySelector<HTMLElement>('#media-grid')!
  const navLinks = root.querySelectorAll<HTMLAnchorElement>('.sidebar-link[data-view]')

  let store = loadChatStore()
  let messages: StoredChatMessage[] = [...getActiveChat(store).messages]
  let isSending = false
  let apiOnline = false
  let activeView: 'chat' | 'media' = 'chat'
  let openMenuChatId: string | null = null
  let renamingChatId: string | null = null

  function closeChatMenu(): void {
    if (!openMenuChatId) {
      return
    }
    openMenuChatId = null
    renderRecents()
  }

  function startRename(chatId: string): void {
    openMenuChatId = null
    renamingChatId = chatId
    renderRecents()
    const input = recentsEl.querySelector<HTMLInputElement>(
      `[data-rename-input="${chatId}"]`,
    )
    input?.focus()
    input?.select()
  }

  function commitRename(chatId: string, value: string): void {
    if (renamingChatId !== chatId) {
      return
    }
    store = renameChat(store, chatId, value)
    saveChatStore(store)
    renamingChatId = null
    renderRecents()
    if (activeView === 'media') {
      void renderMediaLibrary()
    }
  }

  function cancelRename(): void {
    renamingChatId = null
    renderRecents()
  }

  function persistMessages(): void {
    store = upsertActiveChat(store, messages)
    saveChatStore(store)
    renderRecents()
    if (activeView === 'media') {
      void renderMediaLibrary()
    }
  }

  function setView(view: 'chat' | 'media'): void {
    activeView = view
    chatView.hidden = view !== 'chat'
    mediaView.hidden = view !== 'media'

    navLinks.forEach((link) => {
      const isActive = link.dataset.view === view
      link.classList.toggle('active', isActive)
      if (isActive) {
        link.setAttribute('aria-current', 'page')
      } else {
        link.removeAttribute('aria-current')
      }
    })

    if (view === 'media') {
      void renderMediaLibrary()
    }
  }

  async function renderMediaLibrary(): Promise<void> {
    const localItems = collectMediaFromChats(store.chats)
    let serverItems: MediaItem[] = []

    if (apiOnline) {
      try {
        const videos = await listGeneratedVideos()
        serverItems = videos.map((video) => ({
          url: video.url,
          filename: video.filename,
          createdAt: video.created_at * 1000,
        }))
      } catch {
        // Fall back to chat attachments only.
      }
    }

    const items = mergeMediaItems(localItems, serverItems)
    if (!items.length) {
      mediaGrid.innerHTML =
        '<p class="media-empty">No videos yet. Ask Framey to create a short or b-roll montage.</p>'
      return
    }

    mediaGrid.innerHTML = items.map(renderMediaCard).join('')
  }

  function renderRecents(): void {
    const chats = listRecentChats(store).filter(
      (chat) => chat.messages.length > 0 || chat.id === store.activeChatId,
    )

    if (!chats.length) {
      recentsEl.innerHTML = '<p class="sidebar-empty">No conversations yet</p>'
      return
    }

    recentsEl.innerHTML = chats
      .map((chat: SavedChat) => {
        const isRenaming = renamingChatId === chat.id
        const isMenuOpen = openMenuChatId === chat.id
        const titleControl = isRenaming
          ? `<input
              type="text"
              class="sidebar-chat-rename"
              data-rename-input="${escapeHtml(chat.id)}"
              value="${escapeHtml(chat.title)}"
              maxlength="80"
              aria-label="Rename chat"
            />`
          : `<button
              type="button"
              class="sidebar-chat-item${chat.id === store.activeChatId ? ' active' : ''}"
              data-chat-id="${escapeHtml(chat.id)}"
              title="${escapeHtml(chat.title)}"
            >${escapeHtml(chat.title)}</button>`

        return `
          <div class="sidebar-chat-row" role="listitem">
            ${titleControl}
            <div class="sidebar-chat-menu-wrap">
              <button
                type="button"
                class="sidebar-chat-menu-btn"
                data-menu-chat-id="${escapeHtml(chat.id)}"
                aria-label="Chat options"
                aria-expanded="${isMenuOpen ? 'true' : 'false'}"
              >
                <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                  <circle cx="12" cy="5" r="1.75" fill="currentColor"/>
                  <circle cx="12" cy="12" r="1.75" fill="currentColor"/>
                  <circle cx="12" cy="19" r="1.75" fill="currentColor"/>
                </svg>
              </button>
              <div class="sidebar-chat-menu${isMenuOpen ? ' open' : ''}" role="menu">
                <button
                  type="button"
                  class="sidebar-chat-menu-item"
                  role="menuitem"
                  data-chat-action="rename"
                  data-chat-id="${escapeHtml(chat.id)}"
                >Rename</button>
                <button
                  type="button"
                  class="sidebar-chat-menu-item danger"
                  role="menuitem"
                  data-chat-action="delete"
                  data-chat-id="${escapeHtml(chat.id)}"
                >Delete</button>
              </div>
            </div>
          </div>
        `
      })
      .join('')
  }

  function loadActiveChat(): void {
    messages = [...getActiveChat(store).messages]
    updateLayout()
    renderRecents()
  }

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
    statusEl.textContent = 'Framey is ready'
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
      statusEl.textContent = 'Framey is thinking…'
    } else {
      removeThinkingIndicator(log)
      if (apiOnline) {
        statusEl.textContent = 'Framey is ready'
      }
    }
  }

  async function submitMessage(content: string): Promise<void> {
    if (!content || isSending || !apiOnline) {
      return
    }

    messages.push({ role: 'user', content })
    persistMessages()
    updateLayout()
    messageInput.value = ''
    resizeInput()
    setSending(true)

    try {
      const reply = await sendChat(messages)
      messages.push(reply)
      persistMessages()
      renderMessages(log, messages)
      if (reply.attachments?.length) {
        void renderMediaLibrary()
      }
    } catch (error) {
      const detail =
        error instanceof Error ? error.message : 'Something went wrong.'
      messages.push({
        role: 'assistant',
        content: `Sorry, I couldn't respond:\n\n\`${detail}\``,
      })
      persistMessages()
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
    setView('chat')
    store = startNewChat(store)
    saveChatStore(store)
    loadActiveChat()
    messageInput.focus()
  })

  recentsEl.addEventListener('click', (event) => {
    const actionTarget = (event.target as HTMLElement).closest<HTMLButtonElement>(
      '[data-chat-action]',
    )
    if (actionTarget?.dataset.chatAction && actionTarget.dataset.chatId) {
      event.stopPropagation()
      if (isSending) {
        return
      }
      const chatId = actionTarget.dataset.chatId
      if (actionTarget.dataset.chatAction === 'rename') {
        startRename(chatId)
        return
      }
      if (actionTarget.dataset.chatAction === 'delete') {
        openMenuChatId = null
        renamingChatId = null
        store = deleteChat(store, chatId)
        saveChatStore(store)
        loadActiveChat()
        if (activeView === 'media') {
          void renderMediaLibrary()
        }
      }
      return
    }

    const menuTarget = (event.target as HTMLElement).closest<HTMLButtonElement>(
      '[data-menu-chat-id]',
    )
    if (menuTarget?.dataset.menuChatId) {
      event.stopPropagation()
      const chatId = menuTarget.dataset.menuChatId
      openMenuChatId = openMenuChatId === chatId ? null : chatId
      renderRecents()
      return
    }

    const target = (event.target as HTMLElement).closest<HTMLButtonElement>(
      '[data-chat-id]',
    )
    if (!target?.dataset.chatId || isSending) {
      return
    }
    closeChatMenu()
    setView('chat')
    const next = switchChat(store, target.dataset.chatId)
    if (!next) {
      return
    }
    store = next
    saveChatStore(store)
    loadActiveChat()
    messageInput.focus()
  })

  recentsEl.addEventListener('keydown', (event) => {
    const input = event.target as HTMLInputElement
    if (!input.matches('.sidebar-chat-rename') || !input.dataset.renameInput) {
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      commitRename(input.dataset.renameInput, input.value)
    } else if (event.key === 'Escape') {
      event.preventDefault()
      cancelRename()
    }
  })

  recentsEl.addEventListener('focusout', (event) => {
    const input = event.target as HTMLInputElement
    if (!input.matches('.sidebar-chat-rename') || !input.dataset.renameInput) {
      return
    }
    const related = event.relatedTarget as Node | null
    if (related && recentsEl.contains(related)) {
      return
    }
    commitRename(input.dataset.renameInput, input.value)
  })

  document.addEventListener('click', (event) => {
    if (!(event.target instanceof Node)) {
      return
    }
    if (recentsEl.contains(event.target)) {
      return
    }
    closeChatMenu()
  })

  navLinks.forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault()
      const view = link.dataset.view
      if (view === 'chat' || view === 'media') {
        setView(view)
      }
    })
  })

  updateLayout()
  renderRecents()
}
