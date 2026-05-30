import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { JobProgress } from '../components/JobProgress'
import { useToast } from '../components/Toast'
import {
  configureJobWebhook,
  downloadJobOutput,
  getJob,
  type JobSummary,
} from '../lib/api'

export function JobPage() {
  const { jobId = '' } = useParams()
  const { showToast } = useToast()
  const [job, setJob] = useState<JobSummary | null>(null)
  const [webhookUrl, setWebhookUrl] = useState('')
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!jobId) return

    let cancelled = false
    let timer: number | undefined

    async function poll() {
      try {
        const next = await getJob(jobId)
        if (cancelled) return
        setJob(next)
        if (next.status === 'queued' || next.status === 'running') {
          timer = window.setTimeout(poll, 1000)
        }
      } catch (error) {
        showToast(error instanceof Error ? error.message : 'Failed to load job', 'error')
      }
    }

    poll()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [jobId, showToast])

  useEffect(() => {
    return () => {
      if (downloadUrl) URL.revokeObjectURL(downloadUrl)
    }
  }, [downloadUrl])

  async function handleDownload() {
    if (!jobId) return
    try {
      const blob = await downloadJobOutput(jobId)
      const url = URL.createObjectURL(blob)
      setDownloadUrl((current) => {
        if (current) URL.revokeObjectURL(current)
        return url
      })
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Download failed', 'error')
    }
  }

  async function handleWebhook(event: React.FormEvent) {
    event.preventDefault()
    if (!jobId || !webhookUrl) return
    try {
      const updated = await configureJobWebhook(jobId, webhookUrl)
      setJob(updated)
      showToast('Webhook configured.', 'success')
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Webhook failed', 'error')
    }
  }

  if (!job) {
    return <p className="hint">Loading job…</p>
  }

  return (
    <section className="panel">
      <div className="panel__header">
        <h2>Job {job.id.slice(0, 8)}</h2>
        <Link className="text-link" to="/">Back to dashboard</Link>
      </div>

      <dl className="meta-grid">
        <div><dt>Type</dt><dd>{job.job_type}</dd></div>
        <div><dt>Status</dt><dd>{job.status}</dd></div>
        <div><dt>Updated</dt><dd>{new Date(job.updated_at * 1000).toLocaleString()}</dd></div>
        <div><dt>Output</dt><dd>{job.output_filename ?? '—'}</dd></div>
      </dl>

      <JobProgress job={job} />

      {job.error && <p className="banner banner--error">{job.error}</p>}

      {job.status === 'completed' && (
        <div className="result">
          <button type="button" className="button" onClick={handleDownload} data-testid="job-download">
            Download output
          </button>
          {downloadUrl && (
            <a
              className="button button--ghost"
              href={downloadUrl}
              download={job.output_filename ?? 'output'}
              data-testid="job-save"
            >
              Save {job.output_filename ?? 'output'}
            </a>
          )}
        </div>
      )}

      {(job.status === 'queued' || job.status === 'running') && (
        <form className="form form--inline" onSubmit={handleWebhook}>
          <label className="field">
            <span>Webhook URL</span>
            <input type="url" value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} placeholder="https://example.com/hook" />
          </label>
          <button type="submit" className="button button--ghost">Save webhook</button>
        </form>
      )}
    </section>
  )
}
