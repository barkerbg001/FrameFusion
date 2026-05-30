import { useState } from 'react'
import { useToast } from '../components/Toast'
import { loadSettings, saveSettings, type AppSettings } from '../lib/settings'

export function SettingsPage() {
  const { showToast } = useToast()
  const [settings, setSettings] = useState<AppSettings>(loadSettings())

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    saveSettings(settings)
    showToast('Settings saved.', 'success')
  }

  return (
    <section className="panel">
      <h2>Settings</h2>
      <p className="subtitle">Defaults used across creator pages.</p>

      <form className="form" onSubmit={handleSubmit}>
        <label className="field">
          <span>Default output name</span>
          <input
            type="text"
            value={settings.outputName}
            onChange={(e) => setSettings({ ...settings, outputName: e.target.value })}
          />
        </label>
        <label className="field">
          <span>Default lofi duration (minutes): {settings.repeatMinutes}</span>
          <input
            type="range"
            min={1}
            max={180}
            value={settings.repeatMinutes}
            onChange={(e) => setSettings({ ...settings, repeatMinutes: Number(e.target.value) })}
          />
        </label>
        <label className="field">
          <span>Default slideshow FPS: {settings.slideshowFps}</span>
          <input
            type="range"
            min={15}
            max={60}
            value={settings.slideshowFps}
            onChange={(e) => setSettings({ ...settings, slideshowFps: Number(e.target.value) })}
          />
        </label>
        <label className="field">
          <span>Default orientation</span>
          <select
            value={settings.orientation}
            onChange={(e) => setSettings({ ...settings, orientation: e.target.value as AppSettings['orientation'] })}
          >
            <option value="landscape">Landscape</option>
            <option value="portrait">Portrait</option>
          </select>
        </label>
        <label className="field">
          <span>Default seconds per image: {settings.secondsPerImage}</span>
          <input
            type="range"
            min={0.5}
            max={5}
            step={0.5}
            value={settings.secondsPerImage}
            onChange={(e) => setSettings({ ...settings, secondsPerImage: Number(e.target.value) })}
          />
        </label>
        <button type="submit" className="button">Save settings</button>
      </form>
    </section>
  )
}
