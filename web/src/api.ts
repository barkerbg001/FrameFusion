// Typed client for the FrameFusion Django API. All AI and media calls happen on the
// server; the browser only ever sends a key once, when the user saves or tests it.

const API_URL: string = import.meta.env.VITE_API_URL ?? ''

/** Which saved provider/model a group of agents uses. Not a personality. */
export type Route = 'planner' | 'production'
export const ROUTES: Route[] = ['planner', 'production']
/** How the single orchestrator talks. Capabilities are identical. */
export type PersonalityId = 'director' | 'creative_partner'
export type ProviderName = 'openrouter' | 'gemini' | 'anthropic'
export type MediaServiceName = 'elevenlabs' | 'pexels' | 'pixabay' | 'brave'
export type ServiceName = ProviderName | MediaServiceName
export type Theme = 'system' | 'dark' | 'light'
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly payload: Record<string, unknown>

  constructor(message: string, status: number, code: string, payload: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.payload = payload
  }
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]!) : ''
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
  accept?: string
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = { Accept: options.accept ?? 'application/json' }
  let body: BodyInit | undefined
  if (options.body instanceof FormData) {
    body = options.body
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  if (method !== 'GET') {
    headers['X-CSRFToken'] = csrfToken()
  }

  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body,
      credentials: 'include',
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(
      'Cannot reach the FrameFusion server. Check that the API is running.',
      0,
      'network',
      {},
    )
  }
  if (!response.ok) {
    const text = await response.text()
    let data: unknown = null
    try {
      data = text ? JSON.parse(text) : null
    } catch {
      data = null
    }
    const payload = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>
    const message =
      typeof payload.detail === 'string'
        ? payload.detail
        : `The server returned an error (${response.status}).`
    const code = typeof payload.code === 'string' ? payload.code : 'error'
    throw new ApiError(message, response.status, code, payload)
  }
  return response
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options)
  if (response.status === 204) return undefined as T
  const text = await response.text()
  if (!text) return undefined as T
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError('The server sent an unreadable response.', response.status, 'bad_response', {})
  }
}

export function mediaUrl(path: string): string {
  return `${API_URL}${path}`
}

// --- App state, appearance and onboarding -------------------------------------------------

export type OnboardingStep =
  | 'welcome'
  | 'providers'
  | 'models'
  | 'narration'
  | 'media'
  | 'appearance'
  | 'review'

export interface OnboardingState {
  steps: OnboardingStep[]
  step: OnboardingStep
  skipped: OnboardingStep[]
  completed: boolean
  completed_at: string | null
}

export interface IntegrationStatus {
  service: MediaServiceName
  label: string
  configured: boolean
  features: string
}

export interface PersonalityInfo {
  id: PersonalityId
  name: string
  tagline: string
  summary: string
}

export interface AppState {
  theme: Theme
  personality: PersonalityId
  personalities: PersonalityInfo[]
  onboarding: OnboardingState
  encryption_configured: boolean
  readiness: Record<Route, Readiness>
  integrations: Record<MediaServiceName, IntegrationStatus>
  narration: NarrationReadiness
  pending_import_choices: number
}

export interface OnboardingUpdate {
  step?: OnboardingStep
  skip?: OnboardingStep
  complete?: boolean
  restart?: boolean
}

export const app = {
  get: () => request<AppState>('/api/app'),
  setTheme: (theme: Theme) =>
    request<{ theme: Theme }>('/api/settings/appearance', { method: 'PUT', body: { theme } }),
  onboarding: (update: OnboardingUpdate) =>
    request<OnboardingState>('/api/settings/onboarding', { method: 'PUT', body: update }),
  setPersonality: (personality: PersonalityId) =>
    request<{ personality: PersonalityId }>('/api/settings/personality', {
      method: 'PUT',
      body: { personality },
    }),
}

// --- Credentials and AI settings ----------------------------------------------------------

export type CredentialStatus = 'unconfigured' | 'configured' | 'valid' | 'failed'

export interface ProviderCapabilities {
  tools: boolean
  structured_output: boolean
  temperature: boolean
  max_output_tokens: boolean
  model_discovery: boolean
}

export interface ProviderState {
  provider: ServiceName
  kind: 'ai' | 'media'
  label: string
  key_url: string
  docs_url: string
  key_prefix_hint: string
  test_billing_note: string
  features: string
  configured: boolean
  masked_key: string | null
  status: CredentialStatus
  last_test_message: string
  last_tested_at: string | null
  updated_at: string | null
}

export interface ProvidersResponse {
  encryption_configured: boolean
  providers: ProviderState[]
}

export interface ConnectionResult {
  ok: boolean
  message: string
  kind: string | null
  details: Record<string, unknown>
}

export interface TestResponse {
  result: ConnectionResult
  tested: 'saved_key' | 'unsaved_key'
  provider: ProviderState
}

export interface ModelInfo {
  id: string
  label: string
  context_window: number | null
  max_output_tokens: number | null
  supports_tools: boolean | null
  supports_structured_output: boolean | null
  supports_temperature: boolean
  temperature_max: number | null
  source: string
}

export interface ModelsResponse {
  provider: ProviderName
  source: 'live' | 'fallback'
  models: ModelInfo[]
  error: string | null
}

export interface Readiness {
  route: Route
  name: string
  provider: ProviderName | null
  provider_label: string | null
  model: string | null
  source: 'override' | 'default' | 'none'
  ready: boolean
  problem: string | null
}

export interface ModelChoice {
  provider: ProviderName
  model: string
}

export interface AISettings {
  default_provider: ProviderName | null
  default_model: string
  temperature: number | null
  max_output_tokens: number | null
  overrides: Record<Route, ModelChoice | null>
  readiness: Record<Route, Readiness>
  capabilities: Record<ProviderName, ProviderCapabilities>
  notes: { anthropic_temperature_max: number }
}

export interface AISettingsUpdate {
  default_provider: ProviderName | null
  default_model: string
  temperature: number | null
  max_output_tokens: number | null
  overrides: Partial<Record<Route, ModelChoice | null>>
}

export const providers = {
  list: () => request<ProvidersResponse>('/api/settings/providers'),
  saveKey: (provider: ServiceName, apiKey: string) =>
    request<ProviderState>(`/api/settings/providers/${provider}/key`, {
      method: 'PUT',
      body: { api_key: apiKey },
    }),
  removeKey: (provider: ServiceName) =>
    request<ProviderState>(`/api/settings/providers/${provider}/key`, { method: 'DELETE' }),
  test: (provider: ServiceName, apiKey?: string) =>
    request<TestResponse>(`/api/settings/providers/${provider}/test`, {
      method: 'POST',
      body: apiKey ? { api_key: apiKey } : {},
    }),
  models: (provider: ProviderName, refresh = false) =>
    request<ModelsResponse>(
      `/api/settings/providers/${provider}/models${refresh ? '?refresh=1' : ''}`,
    ),
  aiSettings: () => request<AISettings>('/api/settings/ai'),
  saveAISettings: (body: AISettingsUpdate) =>
    request<AISettings>('/api/settings/ai', { method: 'PUT', body }),
}

// --- Media integrations -------------------------------------------------------------------

export interface VoiceSettings {
  stability: number | null
  similarity_boost: number | null
  style: number | null
  speed: number | null
  use_speaker_boost: boolean | null
}

export interface ElevenLabsSettings {
  voice_id: string
  voice_name: string
  model_id: string
  music_model: string
  voice_settings: VoiceSettings
}

export type PexelsMediaType = 'video' | 'photo' | 'both'
export type PexelsOrientation = '' | 'landscape' | 'portrait' | 'square'
export type PexelsSize = '' | 'large' | 'medium' | 'small'

export interface PexelsSettings {
  media_type: PexelsMediaType
  orientation: PexelsOrientation
  size: PexelsSize
}

export interface MediaSettings {
  elevenlabs: ElevenLabsSettings
  pexels: PexelsSettings
  integrations: Record<MediaServiceName, IntegrationStatus>
  music_models: { model_id: string; name: string }[]
}

export interface Voice {
  voice_id: string
  name: string
  category: string
  description: string
  labels: Record<string, string>
  preview_url: string
}

export interface VoicePage {
  voices: Voice[]
  has_more: boolean
  next_page_token: string | null
}

export interface SpeechModel {
  model_id: string
  name: string
  description: string
  source: 'discovered' | 'fallback'
}

export const media = {
  settings: () => request<MediaSettings>('/api/settings/media'),
  saveElevenLabs: (elevenlabs: ElevenLabsSettings) =>
    request<MediaSettings>('/api/settings/media', { method: 'PUT', body: { elevenlabs } }),
  savePexels: (pexels: PexelsSettings) =>
    request<MediaSettings>('/api/settings/media', { method: 'PUT', body: { pexels } }),
  voices: (search = '', nextPageToken: string | null = null) => {
    const query = new URLSearchParams()
    if (search) query.set('search', search)
    if (nextPageToken) query.set('next_page_token', nextPageToken)
    return request<VoicePage>(`/api/settings/media/elevenlabs/voices?${query}`)
  },
  models: () =>
    request<{ models: SpeechModel[]; music_models: { model_id: string; name: string }[] }>(
      '/api/settings/media/elevenlabs/models',
    ),
}

// --- Narration ----------------------------------------------------------------------------

export type NarrationProvider = 'edge' | 'elevenlabs'

export interface NarrationReadiness {
  provider: NarrationProvider
  provider_label: string
  voice: string
  voice_label: string
  ready: boolean
  problem: string | null
  online: boolean
  requires_key: boolean
  source: string
}

export interface EdgeSettings {
  voice: string
  voice_label: string
  rate: number
  pitch: number
  volume: number
}

export interface NarrationProviderInfo {
  id: NarrationProvider
  label: string
  requires_key: boolean
  online: boolean
  configured?: boolean
  disclosure: string
}

export interface NarrationSettings {
  provider: NarrationProvider
  edge: EdgeSettings
  elevenlabs: { voice_id: string; voice_name: string; model_id: string }
  readiness: NarrationReadiness
  providers: NarrationProviderInfo[]
  limits: {
    rate: [number, number]
    pitch: [number, number]
    volume: [number, number]
    preview_max_chars: number
  }
  default_edge_voice: string
}

export interface EdgeVoice {
  id: string
  name: string
  locale: string
  locale_name: string
  gender: string
  status: string
  personalities: string[]
  categories: string[]
}

export interface NarrationPreviewConfig {
  provider?: NarrationProvider
  voice?: string
  voice_label?: string
  rate?: number
  pitch?: number
  volume?: number
}

export interface NarrationPreviewResult {
  preview: {
    url: string
    provider: NarrationProvider
    provider_label: string
    voice: string
    duration_seconds: number | null
    word_timings: number
  }
}

export interface ProjectNarration {
  provider: NarrationProvider | null
  voice: string
  voice_label: string
}

export const narration = {
  settings: () => request<NarrationSettings>('/api/settings/narration'),
  save: (provider: NarrationProvider, edge: EdgeSettings) =>
    request<NarrationSettings>('/api/settings/narration', {
      method: 'PUT',
      body: { provider, edge },
    }),
  edgeVoices: (refresh = false) =>
    request<{ voices: EdgeVoice[]; count: number }>(
      `/api/settings/narration/edge/voices${refresh ? '?refresh=1' : ''}`,
    ),
  preview: (text: string, config: NarrationPreviewConfig) =>
    request<Job>('/api/narration/preview', { method: 'POST', body: { text, config } }),
  retry: (jobId: string, provider?: NarrationProvider) =>
    request<Job>(`/api/jobs/${jobId}/retry-narration`, {
      method: 'POST',
      body: provider ? { provider } : {},
    }),
  setProjectOverride: (projectId: string, value: ProjectNarration | null) =>
    request<Project>(`/api/projects/${projectId}`, {
      method: 'PATCH',
      body: { narration: value ?? { provider: null } },
    }),
}

// --- Settings imported from the multi-account version -------------------------------------

export interface ImportCandidate {
  id: string
  source: string
  summary: string
}

export interface ImportChoice {
  id: number
  group: string
  label: string
  current_summary: string
  source: string
  created_at: string
  candidates: ImportCandidate[]
}

export const imports = {
  list: () => request<{ choices: ImportChoice[] }>('/api/settings/import-conflicts'),
  resolve: (id: number, choice: string) =>
    request<{ choices: ImportChoice[] }>(`/api/settings/import-conflicts/${id}`, {
      method: 'POST',
      body: { choice },
    }),
}

// --- Studio -----------------------------------------------------------------------------

export interface Attachment {
  type: 'video' | 'audio' | 'image'
  url: string
  filename: string
  duration_seconds?: number | null
  id?: string
  download_url?: string
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  /** The personality that wrote an assistant message. */
  persona: PersonalityId | null
  attachments: Attachment[]
  job_id: string | null
  created_at: string
}

export type RightsStatus = 'documented' | 'unknown'

export interface ImageSource {
  provider: string | null
  title: string | null
  source_url: string | null
  source_page_url: string | null
  creator: string | null
  creator_url: string | null
  license: string
  license_url: string | null
  attribution: string | null
  rights_status: RightsStatus
  user_supplied: boolean
  width: number | null
  height: number | null
  checksum: string | null
}

export interface MediaAsset {
  id: string
  kind: 'video' | 'audio' | 'image'
  role: string | null
  file_name: string
  display_name: string
  url: string
  download_url: string
  duration_seconds: number | null
  size_bytes: number | null
  project_id: string | null
  job_id: string | null
  created_at: string
  source?: ImageSource
}

export interface JobEvent {
  seq: number
  type: 'status' | 'thinking' | 'tool' | 'tool_start' | 'step' | 'message' | string
  agent: string | null
  /** Set on orchestrator events only. */
  persona: PersonalityId | null
  message: string
  data: Record<string, unknown>
  created_at: string
}

export interface JobError {
  kind: string
  message: string
  provider?: string
  service?: MediaServiceName
  stage?: Stage
  retryable?: boolean
  retry_after?: number | null
  can_retry_narration?: boolean
  settings_path?: string
}

export type Stage = 'brief' | 'research' | 'script' | 'visuals' | 'narration' | 'music' | 'render' | 'qc'
export type TaskStatus =
  | 'proposed'
  | 'active'
  | 'completed'
  | 'verified'
  | 'failed'
  | 'cancelled'
  | 'skipped'
  | 'invalidated'

export interface ProductionTask {
  id: string
  stage: Stage
  label: string
  specialist: string
  status: TaskStatus
  attempt: number
  max_attempts: number
  artifact_ids: string[]
  limitations: string[]
  error: { kind: string; message: string } | null
  job_id: string | null
  updated_at: string
}

export interface SceneState {
  index: number
  narration: string
  on_screen_text: string
  visual_description: string
  image_query: string
  asset_id: string | null
  selected_by: 'visual' | 'auto' | 'user' | null
  reason: string | null
  gap: string | null
  visual: SceneVisualState
}

export type SceneVisualStatus =
  | 'searching'
  | 'candidates_found'
  | 'awaiting_review'
  | 'selected'
  | 'no_suitable_result'
  | 'download_failed'
  | 'title_card'

export type VisualGapAction =
  | 'search_other_source'
  | 'refine_brief'
  | 'upload'
  | 'paste_url'
  | 'choose_illustrative'
  | 'title_card'

export interface VisualBrief {
  scene_index: number
  purpose: string
  subject: string
  action: string
  named_entities: { name: string; kind: string }[]
  specificity: 'exact' | 'representative' | 'generic'
  visual_type: 'photograph' | 'illustration' | 'diagram' | 'screenshot' | 'background'
  orientation: string
  min_short_side: number
  composition: string
  acceptable_alternatives: string[]
  excluded: string[]
  queries: { query: string; rationale: string }[]
  derived: boolean
}

export type ImageDecision = 'accept' | 'review' | 'illustrative' | 'reject'
export type ImageVerification = 'vision' | 'metadata' | 'none' | 'user'

export interface ImageAssessment {
  candidate_id: string
  decision: ImageDecision
  verification: ImageVerification
  subject_match: 'yes' | 'partial' | 'no' | 'unknown'
  scene_relevance: 'high' | 'medium' | 'low' | 'unknown'
  identity_evidence: string
  composition: string
  technical_quality: string
  rights: RightsStatus
  /** Heuristic for ordering candidates, not a probability. */
  score: number
  visible_content: string
  reasons: string[]
}

export interface SceneAlternative extends ImageCandidate {
  assessment: ImageAssessment
}

export interface SceneVisualState {
  status: SceneVisualStatus | null
  brief: VisualBrief | null
  searches: { query: string; source: string; count: number | null; error: string | null; rationale: string | null }[]
  alternatives: SceneAlternative[]
  assessment: ImageAssessment | null
  note: string
  verification: ImageVerification | null
  rights_status: RightsStatus | null
  illustrative: boolean
  missing: string
  actions: VisualGapAction[]
}

export interface ProductionState {
  tasks: ProductionTask[]
  scenes: SceneState[]
  brief: Record<string, unknown> | null
}

export type ImageSearchSource =
  | 'auto'
  | 'pexels'
  | 'pixabay'
  | 'wikimedia'
  | 'openverse'
  | 'brave'
  | 'url'
  | 'webpage'
  /** A page or image link you paste, for example from a Google Images result you opened yourself. */
  | 'link'

export type ImageProvider = Exclude<ImageSearchSource, 'auto' | 'link'> | 'upload'

export interface ImageCandidate {
  candidate_id: string
  provider: ImageProvider
  title: string
  width: number | null
  height: number | null
  orientation: string | null
  creator: string | null
  license: string
  rights_status: RightsStatus
  source_page_url: string | null
  description: string | null
  tags: string[]
  preview_url: string | null
  creator_url: string | null
  license_url: string | null
  attribution: string | null
  usage_note: string
  user_supplied: boolean
  /** 'google_images' when you found it through Google Images; Google itself is never contacted. */
  discovered_via?: string | null
  publisher?: string | null
  /** Whether the image was seen on the publisher's page. */
  found_on_page?: boolean | null
}

export interface SearchedImage extends ImageCandidate {
  /** Free metadata check against the scene's brief, present when a scene was given. */
  assessment?: ImageAssessment
}

export interface ImageSearchResult {
  query: string
  source: ImageSearchSource
  count: number
  candidates: SearchedImage[]
  limitations: string[]
}

export interface ImageCheckResult {
  scene_index: number
  vision_available: boolean
  assessments: ImageAssessment[]
  limitations: string[]
}

export interface UsageEntry {
  provider: string
  model: string
  calls: number
  input_tokens: number
  output_tokens: number
}

export interface Job {
  id: string
  kind: 'chat' | 'production' | 'agent' | 'render' | 'narration' | 'image_check'
  agent: string | null
  status: JobStatus
  project_id: string | null
  input: Record<string, unknown>
  error: JobError | null
  usage: UsageEntry[]
  cancel_requested: boolean
  retry_of: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  result?: Record<string, unknown> | null
  events?: JobEvent[]
}

export interface Project {
  id: string
  title: string
  title_locked: boolean
  /** Project override; null follows the default from Settings. */
  personality: PersonalityId | null
  effective_personality: PersonalityId
  created_at: string
  updated_at: string
  narration: ProjectNarration
  message_count: number | null
  media_count: number | null
  video_count: number | null
  last_message: string | null
  stage: ProjectStage | null
}

export type ProjectStage = 'idea' | 'developing' | 'in_production' | 'needs_attention' | 'delivered'

export interface ProjectDetail extends Project {
  messages: ChatMessage[]
  jobs: Job[]
  media: MediaAsset[]
  production: ProductionState
}

export interface ProductionOptions {
  task: string
  context?: string
  render_video: boolean
  short_format: 'auto' | 'narrated' | 'silent'
  user_urls?: string[]
}

export interface ImportReport {
  dry_run: boolean
  projects_created: number
  projects_skipped: number
  messages_created: number
  media_claimed: number
  media_skipped: number
  skipped_ids: string[]
}

export interface SpecialistInfo {
  id: string
  name: string
  role: string
  tools: string[]
  produces: string
  reports_to: 'orchestrator'
  route: Route
  route_label: string
}

export interface AgentRegistry {
  orchestrator: {
    id: 'orchestrator'
    name: string
    role: string
    route: Route
    route_label: string
    tools: string[]
    personalities: PersonalityInfo[]
  }
  specialists: SpecialistInfo[]
  services: { id: string; name: string; role: string }[]
}

export const studio = {
  projects: () => request<Project[]>('/api/projects'),
  createProject: (title?: string) =>
    request<Project>('/api/projects', { method: 'POST', body: title ? { title } : {} }),
  project: (id: string) => request<ProjectDetail>(`/api/projects/${id}`),
  renameProject: (id: string, title: string) =>
    request<Project>(`/api/projects/${id}`, { method: 'PATCH', body: { title } }),
  setPersonality: (id: string, personality: PersonalityId | null) =>
    request<Project & { personality_applies: 'now' | 'next_turn' }>(`/api/projects/${id}`, {
      method: 'PATCH',
      body: { personality },
    }),
  rerun: (id: string, fromStage?: Stage) =>
    request<{ message: ChatMessage; job: Job }>(`/api/projects/${id}/production/rerun`, {
      method: 'POST',
      body: fromStage ? { from_stage: fromStage } : {},
    }),
  searchImages: (
    id: string,
    body: {
      query: string
      source: ImageSearchSource
      orientation: 'portrait' | 'landscape' | 'square' | 'any'
      scene_index?: number
    },
  ) => request<ImageSearchResult>(`/api/projects/${id}/images/search`, { method: 'POST', body }),
  /** Starts a paid vision check of search results against the scene's brief. */
  checkImages: (id: string, sceneIndex: number, candidateIds: string[]) =>
    request<Job>(`/api/projects/${id}/images/check`, {
      method: 'POST',
      body: { scene_index: sceneIndex, candidate_ids: candidateIds },
    }),
  downloadImage: (id: string, candidateId: string, sceneIndex: number | null, illustrative = false) =>
    request<{ asset: MediaAsset; reused_existing_file: boolean; production: ProductionState | null }>(
      `/api/projects/${id}/images/download`,
      {
        method: 'POST',
        body:
          sceneIndex === null
            ? { candidate_id: candidateId }
            : { candidate_id: candidateId, scene_index: sceneIndex, illustrative },
      },
    ),
  uploadImage: (id: string, file: File, sceneIndex: number | null) => {
    const form = new FormData()
    form.append('file', file)
    if (sceneIndex !== null) form.append('scene_index', String(sceneIndex))
    return request<{ asset: MediaAsset; reused_existing_file: boolean; production: ProductionState | null }>(
      `/api/projects/${id}/images/upload`,
      { method: 'POST', body: form },
    )
  },
  setSceneImage: (id: string, sceneIndex: number, assetId: string | null) =>
    request<ProductionState>(`/api/projects/${id}/scenes/${sceneIndex}/image`, {
      method: 'PUT',
      body: { asset_id: assetId },
    }),
  useTitleCard: (id: string, sceneIndex: number) =>
    request<ProductionState>(`/api/projects/${id}/scenes/${sceneIndex}/image`, {
      method: 'PUT',
      body: { title_card: true },
    }),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: 'DELETE' }),
  sendMessage: (id: string, content: string) =>
    request<{ message: ChatMessage; job: Job; project: Project }>(
      `/api/projects/${id}/messages`,
      { method: 'POST', body: { content } },
    ),
  runProduction: (id: string, options: ProductionOptions) =>
    request<{ message: ChatMessage; job: Job }>(`/api/projects/${id}/production`, {
      method: 'POST',
      body: options,
    }),
  job: (id: string, after = 0, signal?: AbortSignal) =>
    request<Job>(`/api/jobs/${id}?after=${after}`, { signal }),
  jobs: (params: { project?: string; status?: string; limit?: number } = {}) => {
    const query = new URLSearchParams()
    if (params.project) query.set('project', params.project)
    if (params.status) query.set('status', params.status)
    if (params.limit) query.set('limit', String(params.limit))
    return request<Job[]>(`/api/jobs?${query}`)
  },
  cancelJob: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: 'POST' }),
  media: (kind?: string) => request<MediaAsset[]>(`/api/media${kind ? `?kind=${kind}` : ''}`),
  deleteMedia: (id: string) => request<void>(`/api/media/${id}`, { method: 'DELETE' }),
  agents: () => request<AgentRegistry>('/api/agents/registry'),
  importLegacy: (payload: unknown, dryRun: boolean) =>
    request<ImportReport>(`/api/projects/import-legacy${dryRun ? '?dry_run=1' : ''}`, {
      method: 'POST',
      body: payload,
    }),
}

export function isTerminal(status: JobStatus): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}
