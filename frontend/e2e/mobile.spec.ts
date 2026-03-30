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
    title: 'Portfolio Redesign',
    type_hint: 'project',
    parent_id: null,
    checkin_date: '2026-04-15',
    priority: 1,
    active: true,
    surface: true,
    data: null,
    created_at: '2026-02-01T10:00:00Z',
    updated_at: '2026-03-28T10:00:00Z',
    last_referenced: '2026-03-28T10:00:00Z',
    open_questions: null,
    children_count: 8,
    completed_count: 5,
  },
  {
    id: 'thing-2',
    title: 'AI Agent Beta',
    type_hint: 'project',
    parent_id: null,
    checkin_date: '2026-04-01',
    priority: 1,
    active: true,
    surface: false,
    data: null,
    created_at: '2026-02-15T09:00:00Z',
    updated_at: '2026-03-27T14:00:00Z',
    last_referenced: '2026-03-27T14:00:00Z',
    open_questions: null,
    children_count: 12,
    completed_count: 3,
  },
  {
    id: 'thing-3',
    title: 'Review Q3 Reports',
    type_hint: 'task',
    parent_id: null,
    checkin_date: '2026-03-31',
    priority: 1,
    active: true,
    surface: false,
    data: null,
    created_at: '2026-03-20T08:00:00Z',
    updated_at: '2026-03-29T11:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: 0,
    completed_count: 0,
  },
  {
    id: 'thing-4',
    title: 'Sarah Mitchell',
    type_hint: 'person',
    parent_id: null,
    checkin_date: '2026-04-05',
    priority: 2,
    active: true,
    surface: false,
    data: null,
    created_at: '2026-01-10T10:00:00Z',
    updated_at: '2026-03-25T16:00:00Z',
    last_referenced: '2026-03-25T16:00:00Z',
    open_questions: null,
    children_count: 0,
    completed_count: 0,
  },
  {
    id: 'thing-5',
    title: 'Marcus Williams',
    type_hint: 'person',
    parent_id: null,
    checkin_date: '2026-04-10',
    priority: 3,
    active: true,
    surface: false,
    data: null,
    created_at: '2026-01-15T10:00:00Z',
    updated_at: '2026-03-20T09:00:00Z',
    last_referenced: '2026-03-20T09:00:00Z',
    open_questions: null,
    children_count: 0,
    completed_count: 0,
  },
  {
    id: 'thing-6',
    title: 'Book work holidays',
    type_hint: 'task',
    parent_id: null,
    checkin_date: null,
    priority: 2,
    active: true,
    surface: true,
    data: null,
    created_at: '2026-03-15T10:00:00Z',
    updated_at: '2026-03-28T10:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: 0,
    completed_count: 0,
  },
  {
    id: 'thing-7',
    title: 'Zenith Campaign strategy notes',
    type_hint: 'note',
    parent_id: null,
    checkin_date: null,
    priority: 3,
    active: true,
    surface: false,
    data: null,
    created_at: '2026-03-10T14:00:00Z',
    updated_at: '2026-03-26T11:00:00Z',
    last_referenced: null,
    open_questions: 'What is the final budget allocation?',
    children_count: 0,
    completed_count: 0,
  },
  {
    id: 'thing-8',
    title: 'Client meeting prep checklist',
    type_hint: 'note',
    parent_id: null,
    checkin_date: '2026-03-30',
    priority: 1,
    active: true,
    surface: false,
    data: null,
    created_at: '2026-03-25T09:00:00Z',
    updated_at: '2026-03-29T17:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: 3,
    completed_count: 2,
  },
]

const MOCK_HISTORY = [
  {
    id: 'msg-1',
    role: 'assistant' as const,
    content: 'Good morning! I\'ve analyzed your schedule for today. The **Client Meeting** is approaching. Would you like me to draft a follow-up task list for Sarah now, or after the session?',
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
