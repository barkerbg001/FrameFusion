import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listJobs, type JobSummary } from '../lib/api'
import { useToast } from '../components/Toast'

function formatTime(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString()
}

export function HomePage() {
  const { showToast } = useToast()
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listJobs()
      .then(setJobs)
      .catch((error) => {
        showToast(error instanceof Error ? error.message : 'Failed to load jobs', 'error')
      })
      .finally(() => setLoading(false))
  }, [showToast])

  return (
    <section className="panel">
      <div className="panel__header">
        <h2>Recent jobs</h2>
        <div className="quick-actions">
          <Link className="button button--ghost" to="/lofi">New lofi</Link>
          <Link className="button button--ghost" to="/slideshow">New slideshow</Link>
          <Link className="button button--ghost" to="/shorts">New shorts</Link>
        </div>
      </div>

      {loading && <p className="hint">Loading jobs…</p>}

      {!loading && jobs.length === 0 && (
        <p className="hint">No jobs yet. Start with a creator page above.</p>
      )}

      <ul className="job-list">
        {jobs.map((job) => (
          <li key={job.id}>
            <Link to={`/jobs/${job.id}`} className="job-list__item">
              <div>
                <strong>{job.job_type}</strong>
                <span className={`pill pill--${job.status}`}>{job.status}</span>
              </div>
              <div className="job-list__meta">
                <span>{Math.round(job.progress)}%</span>
                <span>{formatTime(job.updated_at)}</span>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
