import { test, expect, Page } from '@playwright/test'

// Stable mock data — same as visual.spec.ts for consistency
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

async function interceptApi(
  page: Page,
  opts: { things?: boolean; history?: boolean } = {}
) {
  await page.route('**/api/auth/me', route =>
    route.fulfill({ json: MOCK_USER, status: 200 })
  )
  await page.route('**/api/things?*', route =>
    route.fulfill({ json: opts.things ? MOCK_THINGS : [], status: 200 })
  )
  await page.route('**/api/thing-types', route =>
    route.fulfill({ json: [], status: 200 })
  )
  await page.route('**/api/briefing', route =>
    route.fulfill({ json: { things: [], findings: [] }, status: 200 })
  )
  await page.route('**/api/chat/history/**', route =>
    route.fulfill({ json: opts.history ? MOCK_HISTORY : [], status: 200 })
  )
  await page.route('**/api/chat/stats/today', route =>
    route.fulfill({ json: { messages_sent: 0, messages_received: 0 }, status: 200 })
  )
  await page.route('**/api/proactive?*', route =>
    route.fulfill({ json: [], status: 200 })
  )
  await page.route('**/version.json*', route =>
    route.fulfill({ json: { version: '0.0.0' }, status: 200 })
  )
}

const SNAPSHOT_OPTS = { maxDiffPixelRatio: 0.02 }

async function waitForApp(page: Page) {
  // On mobile, wait for the tab bar to appear (always visible when authenticated)
  await page.waitForSelector('nav.fixed.bottom-0', { timeout: 20_000 })
  await page.addStyleTag({
    content: `*, *::before, *::after {
      animation-duration: 0s !important;
      animation-delay: 0s !important;
      transition-duration: 0s !important;
    }`,
  })
  await page.waitForTimeout(500)
}

test.describe('Visual regression – mobile 390×844', () => {
  test('things tab – populated', async ({ page }) => {
    await interceptApi(page, { things: true })
    await page.goto('/')
    await waitForApp(page)

    // Navigate to the Things tab
    await page.click('nav.fixed.bottom-0 button:has-text("Things")')
    await page.waitForTimeout(300)

    await expect(page).toHaveScreenshot('mobile-things-tab-populated.png', {
      ...SNAPSHOT_OPTS,
      animations: 'disabled',
      mask: [page.locator('p.text-xs')],
    })
  })

  test('chat tab – with messages', async ({ page }) => {
    await interceptApi(page, { things: true, history: true })
    await page.goto('/')
    await waitForApp(page)

    // Switch to chat tab
    await page.click('nav.fixed.bottom-0 button:has-text("Chat")')
    await page.waitForTimeout(300)

    await expect(page).toHaveScreenshot('mobile-chat-tab-with-messages.png', {
      ...SNAPSHOT_OPTS,
      animations: 'disabled',
    })
  })
})
