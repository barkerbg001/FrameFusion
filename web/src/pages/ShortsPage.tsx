import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { JobProgress } from '../components/JobProgress'
import { useToast } from '../components/Toast'
import { type JobSummary, waitForJobCompletion } from '../lib/api'
import { loadSettings } from '../lib/settings'
import { uploadFormData } from '../lib/upload'

export function ShortsPage() {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const settings = loadSettings()
  const [images, setImages] = useState<File[]>([])
  const [audio, setAudio] = useState<File | null>(null)
  const [outputName, setOutputName] = useState('shorts.mp4')
  const [orientation, setOrientation] = useState<'landscape' | 'portrait'>(settings.orientation)
  const [secondsPerImage, setSecondsPerImage] = useState(settings.secondsPerImage)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [job, setJob] = useState<JobSummary | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!images.length) {
      showToast('Add at least one image.', 'error')
      return
    }

    setBusy(true)
    setJob(null)
    setUploadProgress(0)

    const form = new FormData()
    for (const image of images) form.append('images', image)
    if (audio) form.append('audio', audio)
    form.append('output_name', outputName)
    form.append('orientation', orientation)
    form.append('seconds_per_image', String(secondsPerImage))
    form.append('shuffle', 'true')
    form.append('fps', '30')

    try {
      const { job_id: jobId } = await uploadFormData({
        endpoint: '/api/shorts/generate',
        form,
        onProgress: setUploadProgress,
      })
      setUploadProgress(null)
      navigate(`/jobs/${jobId}`)
      await waitForJobCompletion(jobId, setJob)
      showToast('Shorts job completed.', 'success')
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Generation failed', 'error')
    } finally {
      setBusy(false)
      setUploadProgress(null)
    }
  }

  return (
    <section className="panel">
      <h2>Shorts creator</h2>
      <p className="subtitle">Fast-cut clips for portrait or landscape short-form video.</p>

      <form className="form" onSubmit={handleSubmit}>
        <label className="field">
          <span>Images</span>
          <input type="file" accept="image/*" multiple onChange={(e) => setImages(Array.from(e.target.files ?? []))} disabled={busy} />
        </label>
        <label className="field">
          <span>Audio (optional)</span>
          <input type="file" accept="audio/*" onChange={(e) => setAudio(e.target.files?.[0] ?? null)} disabled={busy} />
        </label>
        <label className="field">
          <span>Aspect ratio</span>
          <select value={orientation} onChange={(e) => setOrientation(e.target.value as 'landscape' | 'portrait')} disabled={busy}>
            <option value="portrait">Portrait (9:16)</option>
            <option value="landscape">Landscape (16:9)</option>
          </select>
        </label>
        <label className="field">
          <span>Seconds per image: {secondsPerImage}</span>
          <input type="range" min={0.5} max={5} step={0.5} value={secondsPerImage} onChange={(e) => setSecondsPerImage(Number(e.target.value))} disabled={busy} />
        </label>
        <label className="field">
          <span>Output filename</span>
          <input type="text" value={outputName} onChange={(e) => setOutputName(e.target.value)} disabled={busy} />
        </label>

        {(busy || job) && <JobProgress job={job} uploadProgress={uploadProgress} />}

        <button type="submit" className="button" disabled={busy}>Generate shorts</button>
      </form>
    </section>
  )
}
