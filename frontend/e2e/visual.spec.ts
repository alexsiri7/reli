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
    parent_ids: null,
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
    parent_ids: null,
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
    parent_ids: null,
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
  {
    id: 'thing-4',
    title: 'Q2 Product Roadmap',
    type_hint: 'project',
    parent_ids: null,
    checkin_date: '2026-04-25',
    priority: 1,
    active: true,
    surface: false,
    data: null,
    created_at: '2026-03-10T09:00:00Z',
    updated_at: '2026-04-01T09:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: 3,
    completed_count: 1,
  },
  {
    id: 'thing-5',
    title: 'Sarah Mitchell',
    type_hint: 'person',
    parent_ids: null,
    checkin_date: null,
    priority: 2,
    active: true,
    surface: false,
    data: null,
    created_at: '2026-02-15T14:00:00Z',
    updated_at: '2026-03-20T10:00:00Z',
    last_referenced: '2026-04-10T08:00:00Z',
    open_questions: null,
    children_count: 0,
    completed_count: 0,
  },
  {
    id: 'thing-6',
    title: 'Async-first culture experiment',
    type_hint: 'idea',
    parent_ids: null,
    checkin_date: null,
    priority: 3,
    active: true,
    surface: false,
    data: null,
    created_at: '2026-03-22T11:00:00Z',
    updated_at: '2026-03-22T11:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: 0,
    completed_count: 0,
  },
  {
    id: 'thing-7',
    title: 'Team offsite logistics',
    type_hint: 'task',
    parent_ids: ['thing-4'],
    checkin_date: '2026-04-30',
    priority: null,
    active: true,
    surface: true,
    data: null,
    created_at: '2026-04-01T08:00:00Z',
    updated_at: '2026-04-15T12:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: 0,
    completed_count: 0,
  },
]

const MOCK_FINDINGS = [
  {
    id: 'finding-1',
    finding_type: 'stale',
    message: 'No activity in 30 days',
    thing_id: 'thing-3',
    thing: { id: 'thing-3', title: 'Schedule team retrospective' },
    dismissed: false,
    snoozed_until: null,
    priority: 1,
    expires_at: null,
    created_at: '2026-03-01T10:00:00Z',
  },
  {
    id: 'finding-2',
    finding_type: 'approaching_date',
    message: 'Check-in due in 2 days',
    thing_id: 'thing-4',
    thing: { id: 'thing-4', title: 'Q2 Product Roadmap' },
    dismissed: false,
    snoozed_until: null,
    priority: 2,
    expires_at: null,
    created_at: '2026-04-01T10:00:00Z',
  },
  {
    id: 'finding-3',
    finding_type: 'neglected',
    message: 'Last referenced 45 days ago',
    thing_id: 'thing-5',
    thing: { id: 'thing-5', title: 'Sarah Mitchell' },
    dismissed: false,
    snoozed_until: null,
    priority: 3,
    expires_at: null,
    created_at: '2026-04-01T10:00:00Z',
  },
  {
    id: 'finding-4',
    finding_type: 'connection',
    message: 'May relate to Q2 Roadmap',
    thing_id: 'thing-6',
    thing: { id: 'thing-6', title: 'Async-first culture experiment' },
    dismissed: false,
    snoozed_until: null,
    priority: 4,
    expires_at: null,
    created_at: '2026-04-10T10:00:00Z',
  },
]

const MOCK_BRIEFING_PREF = { id: 'pref-1', title: 'Prefers async communication', confidence_label: 'strong' }

const MOCK_HISTORY = [
  {
    id: 'msg-1',
    role: 'assistant' as const,
    content: 'Good morning! You have 3 items due this week and a check-in overdue for the Q2 roadmap.',
    timestamp: '2026-03-14T09:00:00Z',
  },
  {
    id: 'msg-2',
    role: 'user' as const,
    content: 'What should I focus on today?',
    timestamp: '2026-03-14T09:01:00Z',
  },
  {
    id: 'msg-3',
    role: 'assistant' as const,
    content: 'I\'d prioritize **Review pull request for auth module** — it\'s priority 1 and blocking the team. After that, the quarterly report draft needs attention before end of week.',
    timestamp: '2026-03-14T09:01:30Z',
  },
  {
    id: 'msg-4',
    role: 'user' as const,
    content: 'Mark the auth PR review as done',
    timestamp: '2026-03-14T09:05:00Z',
  },
  {
    id: 'msg-5',
    role: 'assistant' as const,
    content: 'Done! I\'ve marked **Review pull request for auth module** as complete. That clears your priority 1 for today.',
    timestamp: '2026-03-14T09:05:05Z',
  },
]

const MOCK_CALENDAR_EVENTS = [
  { id: 'evt-1', summary: 'Q2 Planning Sync', start: '2026-03-14T10:00:00Z', end: '2026-03-14T11:00:00Z', all_day: false, location: 'Conf Room B' },
  { id: 'evt-2', summary: 'Team All-Hands', start: '2026-03-14T14:00:00Z', end: '2026-03-14T15:00:00Z', all_day: false, location: null },
]

/**
 * Intercept all API routes that the app calls on mount.
 * Options control which data is populated vs empty.
 */
async function interceptApi(
  page: Page,
  opts: { things?: boolean; history?: boolean; briefing?: boolean } = {}
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
      json: opts.briefing
        ? {
            date: '2026-03-14',
            the_one_thing: { thing: MOCK_THINGS[0], importance: 3, urgency: 0.9, score: 2.7, reasons: ['Due today'] },
            secondary: [
              { thing: MOCK_THINGS[1], importance: 2, urgency: 0.5, score: 1.0, reasons: ['Check in'] },
              { thing: MOCK_THINGS[6], importance: 1, urgency: 0.3, score: 0.3, reasons: ['Surfaced'] },
            ],
            parking_lot: [],
            findings: MOCK_FINDINGS,
            learned_preferences: [MOCK_BRIEFING_PREF],
            total: 2,
            stats: { active_things: 12, checkin_due: 3, overdue: 1 },
          }
        : {
            the_one_thing: null,
            secondary: [],
            parking_lot: [],
            findings: [],
            learned_preferences: [
              { id: 'pref-1', title: 'Prefers async communication', confidence_label: 'strong' },
              { id: 'pref-2', title: 'Cost-conscious with subscriptions', confidence_label: 'moderate' },
            ],
            total: 0,
            stats: {},
          },
      status: 200,
    })
  )

  // Morning briefing NLP summary
  if (opts.briefing) {
    await page.route('**/api/briefing/morning', route =>
      route.fulfill({
        json: {
          id: 'mb-1',
          content: {
            summary: 'Busy morning — you have 7 items tracked, a proposal draft due, and 3 items to review.',
            priorities: [],
            overdue: [],
            blockers: [],
            findings: [],
          },
          generated_at: '2026-03-14T07:00:00Z',
        },
        status: 200,
      })
    )
    await page.route('**/api/calendar/status', route =>
      route.fulfill({ json: { configured: true, connected: false }, status: 200 })
    )
    await page.route('**/api/calendar/events', route =>
      route.fulfill({ json: { events: MOCK_CALENDAR_EVENTS }, status: 200 })
    )
  }

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

  test('briefing panel – populated (desktop)', async ({ page }) => {
    await interceptApi(page, { things: true, briefing: true })
    await page.setViewportSize({ width: 1280, height: 720 })
    await page.goto('/')
    await waitForApp(page)
    await page.waitForSelector('text=Due Today', { timeout: 5_000 }).catch(() => {})
    const briefingPanel = page.locator('div.flex-1.flex.flex-col').first()
    await expect(briefingPanel).toHaveScreenshot('briefing-panel-populated-desktop.png', {
      ...SNAPSHOT_OPTS, animations: 'disabled',
    })
  })

  test('briefing panel – populated (mobile)', async ({ page }) => {
    await interceptApi(page, { things: true, briefing: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/')
    // Mobile layout uses bottom nav bar instead of aside
    await page.waitForSelector('nav.fixed.bottom-0', { timeout: 20_000 })
    await page.addStyleTag({
      content: `*, *::before, *::after {
      animation-duration: 0s !important;
      animation-delay: 0s !important;
      transition-duration: 0s !important;
    }`,
    })
    await page.waitForTimeout(500)
    await page.waitForSelector('text=Due Today', { timeout: 5_000 }).catch(() => {})
    await expect(page).toHaveScreenshot('briefing-panel-populated-mobile.png', {
      ...SNAPSHOT_OPTS, animations: 'disabled',
    })
  })

  test('briefing panel – populated (dark desktop)', async ({ page }) => {
    await interceptApi(page, { things: true, briefing: true })
    await page.setViewportSize({ width: 1280, height: 720 })
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.goto('/')
    await waitForApp(page)
    await page.waitForSelector('text=Due Today', { timeout: 5_000 }).catch(() => {})
    const briefingPanel = page.locator('div.flex-1.flex.flex-col').first()
    await expect(briefingPanel).toHaveScreenshot('briefing-panel-populated-dark.png', {
      ...SNAPSHOT_OPTS, animations: 'disabled',
    })
  })

  test('sidebar – diverse Things (all types)', async ({ page }) => {
    await interceptApi(page, { things: true })
    await page.goto('/')
    await waitForApp(page)
    await page.waitForSelector('aside h2', { timeout: 5_000 })
    await expect(page.locator('aside').first()).toHaveScreenshot(
      'sidebar-diverse-things.png',
      { ...SNAPSHOT_OPTS, animations: 'disabled' }
    )
  })

  test('full layout – all data populated', async ({ page }) => {
    await interceptApi(page, { things: true, history: true, briefing: true })
    await page.goto('/')
    await waitForApp(page)
    // Wait for briefing panel to render (DUE TODAY section from briefing data)
    await page.waitForSelector('aside h2', { timeout: 5_000 })
    await expect(page).toHaveScreenshot('full-layout-all-populated.png', {
      ...SNAPSHOT_OPTS,
      animations: 'disabled',
      mask: [page.locator('aside p.text-xs')],
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

  test('sidebar – diverse Things (mobile)', async ({ page }) => {
    await interceptApi(page, { things: true })
    // Stub Gmail so the sidebar doesn't show a flaky "Checking Gmail…" state
    await page.route('**/api/gmail/status', route =>
      route.fulfill({ json: { configured: false }, status: 200 })
    )
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/')
    await page.waitForSelector('nav.fixed.bottom-0', { timeout: 20_000 })
    await page.addStyleTag({
      content: `*, *::before, *::after {
      animation-duration: 0s !important;
      animation-delay: 0s !important;
      transition-duration: 0s !important;
    }`,
    })
    await page.waitForTimeout(500)
    // Navigate to Things tab (mobile default is briefing)
    await page.click('nav button:has-text("Things")')
    // Wait for Things content to render (mobile default is Briefing; click switches view)
    await page.waitForTimeout(1_000)
    await expect(page).toHaveScreenshot(
      'sidebar-diverse-things-mobile.png',
      { ...SNAPSHOT_OPTS, animations: 'disabled', mask: [page.locator('p.text-xs')] }
    )
  })

  test('full layout – all data populated (mobile)', async ({ page }) => {
    await interceptApi(page, { things: true, history: true, briefing: true })
    // Stub Gmail so the sidebar doesn't show a flaky "Checking Gmail…" state
    await page.route('**/api/gmail/status', route =>
      route.fulfill({ json: { configured: false }, status: 200 })
    )
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/')
    await page.waitForSelector('nav.fixed.bottom-0', { timeout: 20_000 })
    await page.addStyleTag({
      content: `*, *::before, *::after {
      animation-duration: 0s !important;
      animation-delay: 0s !important;
      transition-duration: 0s !important;
    }`,
    })
    await page.waitForTimeout(500)
    await page.waitForSelector('text=Due Today', { timeout: 5_000 }).catch(() => {})
    await expect(page).toHaveScreenshot('full-layout-all-populated-mobile.png', {
      ...SNAPSHOT_OPTS, animations: 'disabled',
    })
  })
})
