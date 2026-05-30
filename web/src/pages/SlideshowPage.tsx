import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { JobProgress } from '../components/JobProgress'
import { useToast } from '../components/Toast'
import { type JobSummary, waitForJobCompletion } from '../lib/api'
import { loadSettings } from '../lib/settings'
import { uploadFormData } from '../lib/upload'

export function SlideshowPage() {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const settings = loadSettings()
  const [images, setImages] = useState<File[]>([])
  const [audio, setAudio] = useState<File | null>(null)
  const [outputName, setOutputName] = useState('slideshow.mp4')
  const [fps, setFps] = useState(settings.slideshowFps)
  const [orientation, setOrientation] = useState<'landscape' | 'portrait'>(settings.orientation)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [job, setJob] = useState<JobSummary | null>(null)
  const [busy, setBusy] = useState(false)

  function moveImage(index: number, direction: -1 | 1) {
    setImages((current) => {
      const next = [...current]
      const target = index + direction
      if (target < 0 || target >= next.length) return current
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!images.length || !audio) {
      showToast('Add at least one image and an audio track.', 'error')
      return
    }

    setBusy(true)
    setJob(null)
    setUploadProgress(0)

    const form = new FormData()
    for (const image of images) form.append('images', image)
    form.append('audio', audio)
    form.append('output_name', outputName)
    form.append('fps', String(fps))
    form.append('orientation', orientation)

    try {
      const { job_id: jobId } = await uploadFormData({
        endpoint: '/api/slideshow/generate',
        form,
        onProgress: setUploadProgress,
      })
      setUploadProgress(null)
      navigate(`/jobs/${jobId}`)
      await waitForJobCompletion(jobId, setJob)
      showToast('Slideshow job completed.', 'success')
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Generation failed', 'error')
    } finally {
      setBusy(false)
      setUploadProgress(null)
    }
  }

  return (
    <section className="panel">
      <h2>Slideshow creator</h2>
      <p className="subtitle">Upload multiple images, reorder them, and sync to one audio track.</p>

      <form className="form" onSubmit={handleSubmit}>
        <label className="field">
          <span>Images</span>
          <input
            type="file"
            accept="image/*"
            multiple
            onChange={(e) => setImages(Array.from(e.target.files ?? []))}
            disabled={busy}
          />
        </label>

        {images.length > 0 && (
          <ul className="thumb-grid">
            {images.map((image, index) => (
              <li key={`${image.name}-${index}`}>
                <img src={URL.createObjectURL(image)} alt={image.name} />
                <div className="thumb-grid__actions">
                  <button type="button" onClick={() => moveImage(index, -1)} disabled={busy || index === 0}>↑</button>
                  <button type="button" onClick={() => moveImage(index, 1)} disabled={busy || index === images.length - 1}>↓</button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <label className="field">
          <span>Audio track</span>
          <input type="file" accept="audio/*" onChange={(e) => setAudio(e.target.files?.[0] ?? null)} disabled={busy} />
        </label>
        <label className="field">
          <span>Output filename</span>
          <input type="text" value={outputName} onChange={(e) => setOutputName(e.target.value)} disabled={busy} />
        </label>
        <label className="field">
          <span>FPS: {fps}</span>
          <input type="range" min={15} max={60} value={fps} onChange={(e) => setFps(Number(e.target.value))} disabled={busy} />
        </label>
        <label className="field">
          <span>Orientation</span>
          <select value={orientation} onChange={(e) => setOrientation(e.target.value as 'landscape' | 'portrait')} disabled={busy}>
            <option value="landscape">Landscape (16:9)</option>
            <option value="portrait">Portrait (9:16)</option>
          </select>
        </label>

        {(busy || job) && <JobProgress job={job} uploadProgress={uploadProgress} />}

        <button type="submit" className="button" disabled={busy}>Generate slideshow</button>
      </form>
    </section>
  )
}
