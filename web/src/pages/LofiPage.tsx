import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { JobProgress } from '../components/JobProgress'
import { useToast } from '../components/Toast'
import { downloadJobOutput, type JobSummary, waitForJobCompletion } from '../lib/api'
import { loadSettings } from '../lib/settings'
import { uploadFormData } from '../lib/upload'

export function LofiPage() {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const settings = loadSettings()
  const [image, setImage] = useState<File | null>(null)
  const [audio, setAudio] = useState<File | null>(null)
  const [outputName, setOutputName] = useState(settings.outputName)
  const [repeatMinutes, setRepeatMinutes] = useState(settings.repeatMinutes)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [job, setJob] = useState<JobSummary | null>(null)
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    return () => {
      if (downloadUrl) URL.revokeObjectURL(downloadUrl)
    }
  }, [downloadUrl])

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!image || !audio) {
      showToast('Choose an image and audio track.', 'error')
      return
    }

    setBusy(true)
    setJob(null)
    setUploadProgress(0)
    if (downloadUrl) {
      URL.revokeObjectURL(downloadUrl)
      setDownloadUrl(null)
    }

    const form = new FormData()
    form.append('images', image)
    form.append('audio', audio)
    form.append('output_name', outputName)
    form.append('repeat_minutes', String(repeatMinutes))

    try {
      const { job_id: jobId } = await uploadFormData({
        endpoint: '/api/lofi/generate-video',
        form,
        onProgress: setUploadProgress,
      })
      setUploadProgress(null)
      navigate(`/jobs/${jobId}`)
      const completed = await waitForJobCompletion(jobId, setJob)
      const blob = await downloadJobOutput(jobId)
      setDownloadUrl(URL.createObjectURL(blob))
      showToast(`Job ${completed.output_filename ?? 'video'} is ready.`, 'success')
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Generation failed', 'error')
    } finally {
      setBusy(false)
      setUploadProgress(null)
    }
  }

  return (
    <section className="panel">
      <h2>Lofi creator</h2>
      <p className="subtitle">Upload a background image and audio track to generate a looping MP4.</p>

      <form className="form" onSubmit={handleSubmit}>
        <label className="field">
          <span>Background image</span>
          <input
            data-testid="lofi-image-input"
            type="file"
            accept="image/*"
            onChange={(e) => setImage(e.target.files?.[0] ?? null)}
            disabled={busy}
          />
        </label>
        <label className="field">
          <span>Audio track</span>
          <input
            data-testid="lofi-audio-input"
            type="file"
            accept="audio/*"
            onChange={(e) => setAudio(e.target.files?.[0] ?? null)}
            disabled={busy}
          />
        </label>
        <label className="field">
          <span>Output filename</span>
          <input
            data-testid="lofi-output-name"
            type="text"
            value={outputName}
            onChange={(e) => setOutputName(e.target.value)}
            disabled={busy}
          />
        </label>
        <label className="field">
          <span>Duration (minutes): {repeatMinutes}</span>
          <input type="range" min={1} max={180} value={repeatMinutes} onChange={(e) => setRepeatMinutes(Number(e.target.value))} disabled={busy} />
        </label>

        {(busy || job) && (
          <JobProgress job={job} uploadProgress={uploadProgress} label={uploadProgress != null ? 'Upload progress' : 'Render progress'} />
        )}

        <button type="submit" className="button" disabled={busy} data-testid="lofi-submit">
          {busy ? 'Generating…' : 'Generate video'}
        </button>
      </form>

      {downloadUrl && (
        <div className="result">
          <p>Your video is ready.</p>
          <a
            className="button button--ghost"
            href={downloadUrl}
            download={outputName}
            data-testid="lofi-download"
          >
            Download {outputName}
          </a>
          {job && <Link className="text-link" to={`/jobs/${job.id}`}>View job details</Link>}
        </div>
      )}
    </section>
  )
}
