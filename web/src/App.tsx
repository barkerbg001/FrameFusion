import { useEffect, useState } from 'react'
import {
  API_BASE,
  checkHealth,
  generateLofiVideo,
} from './lib/api'
import type { ApiStatus } from './lib/api'
import './App.css'

function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')
  const [image, setImage] = useState<File | null>(null)
  const [audio, setAudio] = useState<File | null>(null)
  const [outputName, setOutputName] = useState('output.mp4')
  const [repeatMinutes, setRepeatMinutes] = useState(60)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    checkHealth()
      .then(() => {
        if (!cancelled) setApiStatus('online')
      })
      .catch(() => {
        if (!cancelled) setApiStatus('offline')
      })

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    return () => {
      if (downloadUrl) URL.revokeObjectURL(downloadUrl)
    }
  }, [downloadUrl])

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)

    if (downloadUrl) {
      URL.revokeObjectURL(downloadUrl)
      setDownloadUrl(null)
    }

    if (!image) {
      setError('Choose an image for the video background.')
      return
    }
    if (!audio) {
      setError('Choose an audio track.')
      return
    }

    setIsGenerating(true)
    try {
      const blob = await generateLofiVideo({
        images: [image],
        audio,
        outputName,
        repeatMinutes,
      })
      setDownloadUrl(URL.createObjectURL(blob))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <p className="eyebrow">FrameFusion</p>
          <h1>Lofi video creator</h1>
          <p className="subtitle">
            Upload a background image and audio track to generate a looping MP4.
          </p>
        </div>
        <div className={`status status--${apiStatus}`}>
          {apiStatus === 'checking' && 'Checking API…'}
          {apiStatus === 'online' && 'API connected'}
          {apiStatus === 'offline' && 'API offline'}
        </div>
      </header>

      {apiStatus === 'offline' && (
        <p className="banner banner--error">
          Cannot reach the API at{' '}
          <code>{API_BASE || 'http://localhost:8000 (via Vite proxy)'}</code>. Start the
          backend with <code>uvicorn app.main:app --reload</code> from the{' '}
          <code>api/</code> folder.
        </p>
      )}

      <form className="form" onSubmit={handleSubmit}>
        <label className="field">
          <span>Background image</span>
          <input
            type="file"
            accept="image/*"
            onChange={(e) => setImage(e.target.files?.[0] ?? null)}
            disabled={isGenerating}
          />
        </label>

        <label className="field">
          <span>Audio track</span>
          <input
            type="file"
            accept="audio/*"
            onChange={(e) => setAudio(e.target.files?.[0] ?? null)}
            disabled={isGenerating}
          />
        </label>

        <label className="field">
          <span>Output filename</span>
          <input
            type="text"
            value={outputName}
            onChange={(e) => setOutputName(e.target.value)}
            disabled={isGenerating}
            placeholder="output.mp4"
          />
        </label>

        <label className="field">
          <span>Duration (minutes): {repeatMinutes}</span>
          <input
            type="range"
            min={1}
            max={180}
            value={repeatMinutes}
            onChange={(e) => setRepeatMinutes(Number(e.target.value))}
            disabled={isGenerating}
          />
        </label>

        {error && <p className="banner banner--error">{error}</p>}

        <button
          type="submit"
          className="submit"
          disabled={isGenerating || apiStatus !== 'online'}
        >
          {isGenerating ? 'Generating video…' : 'Generate video'}
        </button>
      </form>

      {isGenerating && (
        <p className="hint">
          Rendering can take a while for long durations. Keep this tab open.
        </p>
      )}

      {downloadUrl && (
        <section className="result">
          <p>Your video is ready.</p>
          <a className="download" href={downloadUrl} download={outputName}>
            Download {outputName}
          </a>
        </section>
      )}
    </div>
  )
}

export default App
