import { test, expect, Page } from '@playwright/test'

// Stable mock data injected via route interception
const MOCK_USER = {
  id: 'user-1',
  email: 'test@example.com',
  name: 'Test User',
}

const MOCK_THINGS: Record<string, unknown>[] = [
  {
    id: 'thing-1', title: 'Q3 Logistics Proposal', type_hint: 'project',
    parent_ids: null, checkin_date: '2026-04-25', priority: 1, active: true,
    surface: true, data: null,
    created_at: '2026-03-01T10:00:00Z', updated_at: '2026-04-10T10:00:00Z',
    last_referenced: '2026-04-10T10:00:00Z', open_questions: null,
    children_count: 5, completed_count: 3,
  },
  {
    id: 'thing-2', title: 'Sarah Chen — Engineering Lead', type_hint: 'person',
    parent_ids: null, checkin_date: '2026-04-22', priority: 1, active: true,
    surface: false, data: null,
    created_at: '2026-02-15T09:00:00Z', updated_at: '2026-04-15T09:00:00Z',
    last_referenced: '2026-04-15T09:00:00Z', open_questions: null,
    children_count: 0, completed_count: 0,
  },
  {
    id: 'thing-3', title: 'Review auth module PR', type_hint: 'task',
    parent_ids: ['thing-1'], checkin_date: null, priority: 1, active: true,
    surface: false, data: null,
    created_at: '2026-04-01T10:00:00Z', updated_at: '2026-04-01T10:00:00Z',
    last_referenced: null, open_questions: null, children_count: 0, completed_count: 0,
  },
  {
    id: 'thing-4', title: 'Prepare quarterly board slides', type_hint: 'task',
    parent_ids: null, checkin_date: '2026-04-20', priority: 2, active: true,
    surface: false, data: null,
    created_at: '2026-03-20T11:00:00Z', updated_at: '2026-03-20T11:00:00Z',
    last_referenced: null, open_questions: null, children_count: 0, completed_count: 0,
  },
  {
    id: 'thing-5', title: 'Market Alpha competitive analysis notes', type_hint: 'note',
    parent_ids: null, checkin_date: null, priority: 3, active: true,
    surface: false, data: null,
    created_at: '2026-03-10T14:00:00Z', updated_at: '2026-04-05T14:00:00Z',
    last_referenced: '2026-04-05T14:00:00Z', open_questions: null,
    children_count: 0, completed_count: 0,
  },
  {
    id: 'thing-6', title: 'Team retrospective — April', type_hint: 'event',
    parent_ids: null, checkin_date: '2026-04-30', priority: 2, active: true,
    surface: false, data: null,
    created_at: '2026-04-01T12:00:00Z', updated_at: '2026-04-01T12:00:00Z',
    last_referenced: null, open_questions: null, children_count: 0, completed_count: 0,
  },
  {
    id: 'thing-7', title: 'Follow up with vendor on SLA renewal', type_hint: 'task',
    parent_ids: null, checkin_date: '2026-04-19', priority: 1, active: true,
    surface: false, data: null,
    created_at: '2026-04-10T08:00:00Z', updated_at: '2026-04-10T08:00:00Z',
    last_referenced: null, open_questions: null, children_count: 0, completed_count: 0,
  },
]

const MOCK_FINDINGS = [
  {
    id: 'finding-1', finding_type: 'stale',
    message: 'Market Alpha notes haven\'t been touched in 14 days',
    thing_id: 'thing-5', thing: { id: 'thing-5', title: 'Market Alpha competitive analysis notes' },
    dismissed: false, snoozed_until: null, priority: 1, expires_at: null,
    created_at: '2026-04-19T06:00:00Z',
  },
  {
    id: 'finding-2', finding_type: 'approaching_date',
    message: 'SLA renewal follow-up is due today',
    thing_id: 'thing-7', thing: { id: 'thing-7', title: 'Follow up with vendor on SLA renewal' },
    dismissed: false, snoozed_until: null, priority: 1, expires_at: null,
    created_at: '2026-04-19T06:00:00Z',
  },
]

const MOCK_BRIEFING_PREFS = [
  { id: 'pref-1', title: 'Prefers async communication over meetings', confidence_label: 'strong' },
  { id: 'pref-2', title: 'Cost-conscious with vendor contracts', confidence_label: 'moderate' },
]

const MOCK_HISTORY = [
  {
    id: 'msg-1', role: 'assistant' as const,
    content: 'Good morning! You have 3 items due this week. The Q3 Logistics Proposal check-in is coming up on April 25th.',
    timestamp: '2026-04-19T08:00:00Z',
  },
  {
    id: 'msg-2', role: 'user' as const,
    content: 'Can you mark the auth module PR review as done?',
    timestamp: '2026-04-19T08:01:00Z',
  },
  {
    id: 'msg-3', role: 'assistant' as const,
    content: 'Done — I\'ve marked **Review auth module PR** as completed.',
    timestamp: '2026-04-19T08:01:05Z',
  },
  {
    id: 'msg-4', role: 'user' as const,
    content: 'What should I focus on today?',
    timestamp: '2026-04-19T08:02:00Z',
  },
  {
    id: 'msg-5', role: 'assistant' as const,
    content: 'Top priority: **Follow up with vendor on SLA renewal** — it\'s due today. After that, the board slides are due tomorrow.',
    timestamp: '2026-04-19T08:02:08Z',
  },
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
            secondary: [{ thing: MOCK_THINGS[1], importance: 2, urgency: 0.5, score: 1.0, reasons: ['Check in'] }],
            parking_lot: [],
            findings: MOCK_FINDINGS,
            learned_preferences: MOCK_BRIEFING_PREFS,
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
          briefing_date: '2026-04-19',
          content: {
            summary: 'Busy morning — you have a proposal draft due and 3 items to review.',
            priorities: [], overdue: [], blockers: [], findings: [], stats: {},
          },
          generated_at: '2026-04-19T07:00:00Z',
        },
        status: 200,
      })
    )
    await page.route('**/api/calendar/status', route =>
      route.fulfill({ json: { configured: true, connected: false }, status: 200 })
    )
    await page.route('**/api/calendar/events', route =>
      route.fulfill({ json: { events: [] }, status: 200 })
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
    await page.waitForTimeout(1000)
    await expect(page).toHaveScreenshot('briefing-panel-populated-desktop.png', {
      ...SNAPSHOT_OPTS, animations: 'disabled', timeout: 15_000,
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
    await page.waitForSelector('text=Daily Briefing', { timeout: 10_000 }).catch(() => {})
    await page.waitForTimeout(1000)
    await expect(page).toHaveScreenshot('briefing-panel-populated-dark.png', {
      ...SNAPSHOT_OPTS, animations: 'disabled', timeout: 15_000,
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
