import type { JobSummary } from '../lib/api'

type JobProgressProps = {
  job: JobSummary | null
  uploadProgress?: number | null
  label?: string
}

export function JobProgress({ job, uploadProgress, label = 'Render progress' }: JobProgressProps) {
  const progress = job?.progress ?? uploadProgress ?? 0
  const status = job?.status ?? (uploadProgress != null ? 'uploading' : 'queued')

  return (
    <div className="progress-card">
      <div className="progress-card__header">
        <span>{label}</span>
        <span className="progress-card__status">{status}</span>
      </div>
      <div className="progress-bar">
        <div className="progress-bar__fill" style={{ width: `${Math.min(100, progress)}%` }} />
      </div>
      <p className="progress-card__value">{Math.round(progress)}%</p>
    </div>
  )
}
