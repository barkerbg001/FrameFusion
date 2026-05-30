import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ToastProvider } from './components/Toast'
import { HomePage } from './pages/HomePage'
import { JobPage } from './pages/JobPage'
import { LofiPage } from './pages/LofiPage'
import { SettingsPage } from './pages/SettingsPage'
import { ShortsPage } from './pages/ShortsPage'
import { SlideshowPage } from './pages/SlideshowPage'

export default function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="lofi" element={<LofiPage />} />
            <Route path="slideshow" element={<SlideshowPage />} />
            <Route path="shorts" element={<ShortsPage />} />
            <Route path="jobs/:jobId" element={<JobPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  )
}
