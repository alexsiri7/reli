import { test, expect, Page } from '@playwright/test'

// Stable mock data injected via route interception
const MOCK_USER = {
  id: 'user-1',
  email: 'test@example.com',
  name: 'Test User',
}

const MOCK_THINGS: Record<string, unknown>[] = [
  {
    id: 'thing-1',
    title: 'Review pull request for auth module',
    type_hint: 'task',
    parent_id: null,
    checkin_date: null,
    priority: 1,
    active: true,
    surface: false,
    data: null,
    created_at: '2026-03-01T10:00:00Z',
    updated_at: '2026-03-01T10:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: 0,
    completed_count: 0,
  },
  {
    id: 'thing-2',
    title: 'Prepare quarterly report',
    type_hint: 'task',
    parent_id: null,
    checkin_date: '2026-03-20',
    priority: 2,
    active: true,
    surface: false,
    data: null,
    created_at: '2026-03-01T11:00:00Z',
    updated_at: '2026-03-01T11:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: 0,
    completed_count: 0,
  },
  {
    id: 'thing-3',
    title: 'Schedule team retrospective',
    type_hint: 'note',
    parent_id: null,
    checkin_date: '2026-03-25',
    priority: 3,
    active: true,
    surface: false,
    data: null,
    created_at: '2026-03-01T12:00:00Z',
    updated_at: '2026-03-01T12:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: 0,
    completed_count: 0,
  },
]

const MOCK_HISTORY = [
  {
    id: 'msg-1',
    role: 'assistant' as const,
    content: 'Hello! How can I help you track your Things today?',
    timestamp: '2026-03-14T09:00:00Z',
  },
]

/**
 * Intercept all API routes that the app calls on mount.
 * Options control which data is populated vs empty.
 */
async function interceptApi(
  page: Page,
  opts: { things?: boolean; history?: boolean } = {}
) {
  // Auth — always return a valid user so the app renders the main UI
  await page.route('**/api/auth/me', route =>
    route.fulfill({ json: MOCK_USER, status: 200 })
  )

  // Things
  await page.route('**/api/things?*', route =>
    route.fulfill({ json: opts.things ? MOCK_THINGS : [], status: 200 })
  )

  // Thing types
  await page.route('**/api/thing-types', route =>
    route.fulfill({ json: [], status: 200 })
  )

  // Briefing
  await page.route('**/api/briefing', route =>
    route.fulfill({ json: { things: [], findings: [] }, status: 200 })
  )

  // Chat history (session ID is dynamic, match any)
  await page.route('**/api/chat/history/**', route =>
    route.fulfill({ json: opts.history ? MOCK_HISTORY : [], status: 200 })
  )

  // Daily stats
  await page.route('**/api/chat/stats/today', route =>
    route.fulfill({
      json: { messages_sent: 0, messages_received: 0 },
      status: 200,
    })
  )

  // Proactive surfaces
  await page.route('**/api/proactive?*', route =>
    route.fulfill({ json: [], status: 200 })
  )

  // Version check (prevent network requests)
  await page.route('**/version.json*', route =>
    route.fulfill({ json: { version: '0.0.0' }, status: 200 })
  )
}

/** Shared snapshot options — tolerate minor sub-pixel rendering differences */
const SNAPSHOT_OPTS = { maxDiffPixelRatio: 0.02 }

async function waitForApp(page: Page) {
  // App renders aside in both desktop and mobile layout divs; wait for first one
  await page.waitForSelector('aside', { timeout: 20_000 })
  // Disable animations for deterministic snapshots
  await page.addStyleTag({
    content: `*, *::before, *::after {
      animation-duration: 0s !important;
      animation-delay: 0s !important;
      transition-duration: 0s !important;
    }`,
  })
  // Let layout settle
  await page.waitForTimeout(500)
}

test.describe('Visual regression – reli frontend', () => {
  test('full layout – empty state', async ({ page }) => {
    await interceptApi(page)
    await page.goto('/')
    await waitForApp(page)

    await expect(page).toHaveScreenshot('full-layout-empty.png', {
      ...SNAPSHOT_OPTS,
      animations: 'disabled',
      mask: [page.locator('aside p.text-xs')],
    })
  })

  test('sidebar – empty (no Things)', async ({ page }) => {
    await interceptApi(page)
    await page.goto('/')
    await waitForApp(page)

    // Use .first() because the app renders aside in both desktop and mobile layout divs
    await expect(page.locator('aside').first()).toHaveScreenshot('sidebar-empty.png', {
      ...SNAPSHOT_OPTS,
      animations: 'disabled',
      mask: [page.locator('aside').first().locator('p.text-xs')],
    })
  })

  test('sidebar – with Things listed', async ({ page }) => {
    await interceptApi(page, { things: true })
    await page.goto('/')
    await waitForApp(page)
    // Wait for Things to render
    await page.waitForSelector('aside h2', { timeout: 5_000 })

    // Use .first() because the app renders aside in both desktop and mobile layout divs
    await expect(page.locator('aside').first()).toHaveScreenshot(
      'sidebar-with-things.png',
      {
        ...SNAPSHOT_OPTS,
        animations: 'disabled',
        mask: [page.locator('aside').first().locator('p.text-xs')],
      }
    )
  })

  test('chat panel – empty messages state', async ({ page }) => {
    await interceptApi(page)
    await page.goto('/')
    await waitForApp(page)

    // Chat panel is the main flex column next to sidebar
    const chatPanel = page.locator('div.flex-1.flex.flex-col').first()
    await expect(chatPanel).toHaveScreenshot('chat-panel-empty.png', {
      ...SNAPSHOT_OPTS,
      animations: 'disabled',
    })
  })

  test('chat panel – with messages', async ({ page }) => {
    await interceptApi(page, { history: true })
    await page.goto('/')
    await waitForApp(page)
    // Wait for history to render
    await page
      .waitForSelector('[class*="rounded-2xl"]', { timeout: 5_000 })
      .catch(() => {})

    const chatPanel = page.locator('div.flex-1.flex.flex-col').first()
    await expect(chatPanel).toHaveScreenshot('chat-panel-with-messages.png', {
      ...SNAPSHOT_OPTS,
      animations: 'disabled',
    })
  })

  test('full layout – with Things and messages', async ({ page }) => {
    await interceptApi(page, { things: true, history: true })
    await page.goto('/')
    await waitForApp(page)
    await page.waitForSelector('aside h2', { timeout: 5_000 })

    await expect(page).toHaveScreenshot('full-layout-populated.png', {
      ...SNAPSHOT_OPTS,
      animations: 'disabled',
      mask: [page.locator('aside p.text-xs')],
    })
  })
})
