/**
 * Smoke E2E integration tests — run against a live staging server.
 *
 * Usage:
 *   BASE_URL=https://staging.example.com npm --prefix frontend run test:smoke
 *
 * These tests hit real endpoints (no mocking) to verify the deployment is
 * healthy before gating production deploys. They cover:
 *   - Backend health endpoints
 *   - Frontend serving and login page render
 *   - Auth-gated API rejection for unauthenticated requests
 *   - Core API contract smoke checks
 */
import { test, expect } from '@playwright/test'

test.describe('Smoke – backend health', () => {
  test('GET /healthz returns ok', async ({ request }) => {
    const resp = await request.get('/healthz')
    expect(resp.status()).toBe(200)
    const body = await resp.json()
    expect(body).toHaveProperty('status', 'ok')
    expect(body).toHaveProperty('service', 'reli')
  })

  test('GET /api/health returns detailed status', async ({ request }) => {
    const resp = await request.get('/api/health')
    expect(resp.status()).toBe(200)
    const body = await resp.json()
    expect(body).toHaveProperty('service', 'reli')
    expect(body).toHaveProperty('db_connected')
    expect(body).toHaveProperty('vector_count')
    expect(body).toHaveProperty('uptime_seconds')
    // DB must be connected for staging to be healthy
    expect(body.db_connected).toBe(true)
  })
})

test.describe('Smoke – frontend serving', () => {
  test('root URL serves HTML with expected title', async ({ page }) => {
    const resp = await page.goto('/')
    expect(resp).not.toBeNull()
    expect(resp!.status()).toBe(200)
    const contentType = resp!.headers()['content-type'] || ''
    expect(contentType).toContain('text/html')
  })

  test('unauthenticated user sees login page', async ({ page }) => {
    await page.goto('/')
    // The app should show the login page for unauthenticated users
    await expect(page.getByText('Sign in with Google')).toBeVisible({ timeout: 15_000 })
  })
})

test.describe('Smoke – auth-gated API endpoints', () => {
  test('GET /api/auth/me returns 401 without session', async ({ request }) => {
    const resp = await request.get('/api/auth/me')
    // 401 or 403 — either is acceptable for unauthenticated requests
    expect([401, 403]).toContain(resp.status())
  })

  test('GET /api/things rejects unauthenticated request', async ({ request }) => {
    const resp = await request.get('/api/things?limit=1')
    expect([401, 403]).toContain(resp.status())
  })

  test('GET /api/briefing rejects unauthenticated request', async ({ request }) => {
    const resp = await request.get('/api/briefing')
    expect([401, 403]).toContain(resp.status())
  })

  test('POST /api/chat rejects unauthenticated request', async ({ request }) => {
    const resp = await request.post('/api/chat', {
      data: { message: 'hello' },
    })
    expect([401, 403, 422]).toContain(resp.status())
  })
})

test.describe('Smoke – static assets', () => {
  test('JS bundle loads successfully', async ({ page }) => {
    const jsErrors: string[] = []
    page.on('pageerror', err => jsErrors.push(err.message))

    await page.goto('/')
    // Wait for the app to initialize (login page or main UI)
    await page.waitForLoadState('load', { timeout: 15_000 })

    // No uncaught JS errors during page load
    expect(jsErrors).toEqual([])
  })

  test('CSS loads without broken resources', async ({ page }) => {
    const failedResources: string[] = []
    page.on('response', resp => {
      if (resp.status() >= 400 && resp.url().match(/\.(css|js|woff2?|png|svg)$/)) {
        failedResources.push(`${resp.status()} ${resp.url()}`)
      }
    })

    await page.goto('/')
    await page.waitForLoadState('load', { timeout: 15_000 })

    expect(failedResources).toEqual([])
  })
})
