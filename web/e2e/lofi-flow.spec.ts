import { expect, test } from '@playwright/test'
import { join } from 'node:path'

const fixturesDir = join(import.meta.dirname, 'fixtures')

test.describe('Lofi workflow', () => {
  test('uploads media, waits for job completion, and downloads output', async ({ page }) => {
    await page.goto('/lofi')

    await expect(page.getByRole('heading', { name: 'Lofi creator' })).toBeVisible()

    await page.getByTestId('lofi-image-input').setInputFiles(join(fixturesDir, 'test.png'))
    await page.getByTestId('lofi-audio-input').setInputFiles(join(fixturesDir, 'test.wav'))
    await page.getByTestId('lofi-output-name').fill('e2e-output.mp4')

    await page.getByTestId('lofi-submit').click()

    await expect(page.getByRole('heading', { name: /^Job / })).toBeVisible()
    await expect(page.locator('dd', { hasText: 'completed' })).toBeVisible({ timeout: 30_000 })

    await page.getByTestId('job-download').click()
    await expect(page.getByTestId('job-save')).toBeVisible({ timeout: 10_000 })

    const downloadPromise = page.waitForEvent('download')
    await page.getByTestId('job-save').click()
    const download = await downloadPromise

    expect(download.suggestedFilename()).toBe('e2e-output.mp4')
    const path = await download.path()
    expect(path).toBeTruthy()
  })
})
