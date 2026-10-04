import { ApiError, isTerminal, studio, type Job, type JobEvent } from './api.ts'

export interface JobWatcher {
  stop(): void
}

interface WatchOptions {
  after?: number
  onUpdate(job: Job, newEvents: JobEvent[]): void
  onDone?(job: Job): void
  onError?(error: ApiError): void
}

// Polls /api/jobs/<id> for new events until the job finishes. Fast at first, then
// slower; slower still while the tab is hidden; backs off on network errors.
export function watchJob(jobId: string, options: WatchOptions): JobWatcher {
  let after = options.after ?? 0
  let stopped = false
  let timer = 0
  let failures = 0
  const controller = new AbortController()
  const started = Date.now()

  const delay = (): number => {
    if (failures > 0) return Math.min(8000, 1000 * 2 ** failures)
    if (document.hidden) return 5000
    return Date.now() - started < 15_000 ? 900 : 2000
  }

  const tick = async (): Promise<void> => {
    if (stopped) return
    try {
      const job = await studio.job(jobId, after, controller.signal)
      failures = 0
      const events = job.events ?? []
      if (events.length) after = events[events.length - 1]!.seq
      options.onUpdate(job, events)
      if (isTerminal(job.status)) {
        stopped = true
        options.onDone?.(job)
        return
      }
    } catch (error) {
      if (stopped || (error instanceof DOMException && error.name === 'AbortError')) return
      failures += 1
      if (error instanceof ApiError && error.status === 404) {
        stopped = true
        options.onError?.(error)
        return
      }
      if (error instanceof ApiError && failures === 3) options.onError?.(error)
    }
    if (!stopped) timer = window.setTimeout(() => void tick(), delay())
  }

  timer = window.setTimeout(() => void tick(), 300)
  return {
    stop() {
      stopped = true
      window.clearTimeout(timer)
      controller.abort()
    },
  }
}
