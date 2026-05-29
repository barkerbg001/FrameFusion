import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('App', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the lofi creator and connects to the API', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'ok',
        paths: { uploads: '/uploads', output: '/output' },
      }),
    } as Response)

    render(<App />)

    expect(
      screen.getByRole('heading', { name: /lofi video creator/i }),
    ).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByText(/API connected/i)).toBeInTheDocument()
    })
  })
})
