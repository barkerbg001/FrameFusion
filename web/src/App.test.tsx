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

  it('renders the dashboard and connects to the API', async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/health')) {
        return {
          ok: true,
          json: async () => ({
            status: 'ok',
            paths: { uploads: '/uploads', output: '/output' },
          }),
        } as Response
      }
      if (url.includes('/api/jobs')) {
        return {
          ok: true,
          json: async () => [],
        } as Response
      }
      throw new Error(`Unexpected fetch: ${url}`)
    })

    render(<App />)

    expect(screen.getByRole('heading', { name: /video studio/i })).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByText(/API connected/i)).toBeInTheDocument()
    })
  })
})
