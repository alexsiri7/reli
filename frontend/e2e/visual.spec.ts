import { test, expect, Page } from '@playwright/test'

// Stable mock data injected via route interception
const MOCK_THINGS = [
  {
    id: 'thing-1',
    name: 'Review pull request for auth module',
    notes: 'Needs security review',
    checkin_date: null,
    created_at: '2026-03-01T10:00:00Z',
    updated_at: '2026-03-01T10:00:00Z',
  },
  {
    id: 'thing-2',
    name: 'Prepare quarterly report',
    notes: 'Due end of month',
    checkin_date: '2026-03-20',
    created_at: '2026-03-01T11:00:00Z',
    updated_at: '2026-03-01T11:00:00Z',
  },
  {
    id: 'thing-3',
    name: 'Schedule team retrospective',
    notes: null,
    checkin_date: '2026-03-25',
    created_at: '2026-03-01T12:00:00Z',
    updated_at: '2026-03-01T12:00:00Z',
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

async function interceptApiWithThings(page: Page) {
  await page.route('/things', route =>
    route.fulfill({ json: MOCK_THINGS, status: 200 })
  )
  await page.route('/briefing', route =>
    route.fulfill({ json: [], status: 200 })
  )
  await page.route('/history', route =>
    route.fulfill({ json: [], status: 200 })
  )
}

async function interceptApiEmpty(page: Page) {
  await page.route('/things', route =>
    route.fulfill({ json: [], status: 200 })
  )
  await page.route('/briefing', route =>
    route.fulfill({ json: [], status: 200 })
  )
  await page.route('/history', route =>
    route.fulfill({ json: [], status: 200 })
  )
}

async function interceptApiWithHistory(page: Page) {
  await page.route('/things', route =>
    route.fulfill({ json: [], status: 200 })
  )
  await page.route('/briefing', route =>
    route.fulfill({ json: [], status: 200 })
  )
  await page.route('/history', route =>
    route.fulfill({ json: MOCK_HISTORY, status: 200 })
  )
}

async function waitForApp(page: Page) {
  await page.waitForSelector('aside', { timeout: 20_000 })
  // Disable animations for deterministic snapshots
  await page.addStyleTag({
    content: `*, *::before, *::after {
      animation-duration: 0s !important;
      animation-delay: 0s !important;
      transition-duration: 0s !important;
    }`,
  })
}

test.describe('Visual regression – reli frontend', () => {
  test('full layout – empty state', async ({ page }) => {
    await interceptApiEmpty(page)
    await page.goto('/')
    await waitForApp(page)

    await expect(page).toHaveScreenshot('full-layout-empty.png', {
      animations: 'disabled',
      mask: [page.locator('aside p.text-xs')],
    })
  })

  test('sidebar – empty (no Things)', async ({ page }) => {
    await interceptApiEmpty(page)
    await page.goto('/')
    await waitForApp(page)

    await expect(page.locator('aside')).toHaveScreenshot('sidebar-empty.png', {
      animations: 'disabled',
      mask: [page.locator('aside p.text-xs')],
    })
  })

  test('sidebar – with Things listed', async ({ page }) => {
    await interceptApiWithThings(page)
    await page.goto('/')
    await waitForApp(page)
    // Wait for Things to render
    await page.waitForSelector('aside h2', { timeout: 5_000 })

    await expect(page.locator('aside')).toHaveScreenshot('sidebar-with-things.png', {
      animations: 'disabled',
      mask: [page.locator('aside p.text-xs')],
    })
  })

  test('chat panel – empty messages state', async ({ page }) => {
    await interceptApiEmpty(page)
    await page.goto('/')
    await waitForApp(page)

    // Chat panel is the main flex column next to sidebar
    const chatPanel = page.locator('div.flex-1.flex.flex-col').first()
    await expect(chatPanel).toHaveScreenshot('chat-panel-empty.png', {
      animations: 'disabled',
    })
  })

  test('chat panel – with messages', async ({ page }) => {
    await interceptApiWithHistory(page)
    await page.goto('/')
    await waitForApp(page)
    // Wait for history to render
    await page.waitForSelector('[class*="rounded-2xl"]', { timeout: 5_000 }).catch(() => {})

    const chatPanel = page.locator('div.flex-1.flex.flex-col').first()
    await expect(chatPanel).toHaveScreenshot('chat-panel-with-messages.png', {
      animations: 'disabled',
    })
  })

  test('full layout – with Things and messages', async ({ page }) => {
    await page.route('/things', route =>
      route.fulfill({ json: MOCK_THINGS, status: 200 })
    )
    await page.route('/briefing', route =>
      route.fulfill({ json: [], status: 200 })
    )
    await page.route('/history', route =>
      route.fulfill({ json: MOCK_HISTORY, status: 200 })
    )

    await page.goto('/')
    await waitForApp(page)
    await page.waitForSelector('aside h2', { timeout: 5_000 })

    await expect(page).toHaveScreenshot('full-layout-populated.png', {
      animations: 'disabled',
      mask: [page.locator('aside p.text-xs')],
    })
  })
})
