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
  {
    id: 'msg-2',
    role: 'user' as const,
    content: 'Please add a new task: "Follow up with Sarah regarding the campaign budget".',
    timestamp: '2026-03-14T09:01:00Z',
  },
  {
    id: 'msg-3',
    role: 'assistant' as const,
    content: 'Done! I\'ve added that to your active task list.\n\n**Action Applied** — New task synced to briefing:\n- *Task:* Follow up with Sarah regarding budget\n- *Project:* Zenith Campaign',
    timestamp: '2026-03-14T09:01:10Z',
  },
  {
    id: 'msg-4',
    role: 'user' as const,
    content: 'What\'s the status on the Portfolio Redesign?',
    timestamp: '2026-03-14T09:03:00Z',
  },
  {
    id: 'msg-5',
    role: 'assistant' as const,
    content: 'The **Portfolio Redesign** is 63% complete (5 of 8 sub-tasks done). Remaining items:\n\n1. Finalize responsive breakpoints\n2. Accessibility audit\n3. Performance optimization\n\nThe check-in date is April 15. You\'re on track.',
    timestamp: '2026-03-14T09:03:15Z',
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
    route.fulfill({
      json: {
        things: opts.things ? MOCK_THINGS.slice(0, 3) : [],
        findings: opts.things
          ? [
              {
                id: 'f-1',
                finding_type: 'approaching_date',
                message: 'Client meeting prep checklist is due tomorrow',
                thing_id: 'thing-8',
                thing: { id: 'thing-8', title: 'Client meeting prep checklist', type_hint: 'note' },
              },
              {
                id: 'f-2',
                finding_type: 'stale',
                message: 'Zenith Campaign strategy notes haven\'t been updated in 4 days',
                thing_id: 'thing-7',
                thing: { id: 'thing-7', title: 'Zenith Campaign strategy notes', type_hint: 'note' },
              },
              {
                id: 'f-3',
                finding_type: 'open_question',
                message: 'Open question on Zenith Campaign: "What is the final budget allocation?"',
                thing_id: 'thing-7',
                thing: { id: 'thing-7', title: 'Zenith Campaign strategy notes', type_hint: 'note' },
              },
            ]
          : [],
      },
      status: 200,
    })
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
