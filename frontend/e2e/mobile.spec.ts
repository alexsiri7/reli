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

/** Wait until `selector`'s bounding box is unchanged across two animation frames. */
async function waitForLayoutStable(page: Page, selector: string, timeout = 5_000) {
  await page.waitForFunction(
    sel => {
      const el = document.querySelector(sel)
      if (!el) return false
      const rect = el.getBoundingClientRect()
      const key = '__reli_layout_check__'
      const prev = (window as unknown as Record<string, unknown>)[key] as
        | { sel: string; top: number; left: number; width: number; height: number }
        | undefined
      ;(window as unknown as Record<string, unknown>)[key] = {
        sel,
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
      }
      if (!prev || prev.sel !== sel) return false
      return (
        prev.top === rect.top &&
        prev.left === rect.left &&
        prev.width === rect.width &&
        prev.height === rect.height
      )
    },
    selector,
    { polling: 'raf', timeout }
  )
}

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
  await waitForLayoutStable(page, 'nav.fixed.bottom-0')
}

test.describe('Visual regression – mobile 390×844', () => {
  test('things tab – populated', async ({ page }) => {
    await interceptApi(page, { things: true })
    await page.goto('/')
    await waitForApp(page)

    // Navigate to the Things tab
    await page.click('nav.fixed.bottom-0 button:has-text("Things")')
    // Desktop and mobile layouts both mount a Sidebar; :visible filters to the one actually shown
    await page.waitForSelector('p:visible:has-text("Review pull request for auth module")')

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
    // Desktop and mobile layouts both mount a ChatPanel; :visible filters to the one actually shown
    await page.waitForSelector('[class*="rounded-2xl"]:visible')

    await expect(page).toHaveScreenshot('mobile-chat-tab-with-messages.png', {
      ...SNAPSHOT_OPTS,
      animations: 'disabled',
    })
  })

  test('briefing tab – populated', async ({ page }) => {
    const MOCK_THING = {
      id: 'briefing-thing-1',
      title: 'Finish the auth module refactor',
      type_hint: 'task',
      parent_ids: null,
      checkin_date: '2026-04-20',
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
    }
    await interceptApi(page, { things: true })
    // Registered after interceptApi so this specific mock takes priority over
    // its generic `/api/briefing` route (Playwright runs the latest-registered
    // handler first).
    await page.route('**/api/briefing', route =>
      route.fulfill({
        json: {
          the_one_thing: {
            thing: MOCK_THING,
            reasons: ['Overdue by 3 days'],
            importance: 3,
            urgency: 3,
            score: 0.91,
          },
          secondary: [],
          findings: [],
          learned_preferences: [],
          stats: { active_things: 12, checkin_due: 3, overdue: 1 },
        },
        status: 200,
      })
    )
    await page.goto('/')
    await waitForApp(page)

    // Navigate to the Briefing tab
    await page.click('nav.fixed.bottom-0 button:has-text("Briefing")')
    // Desktop and mobile layouts both mount a BriefingPanel; :visible filters to the one actually shown
    await page.waitForSelector('h3:visible:has-text("Finish the auth module refactor")')

    await expect(page).toHaveScreenshot('mobile-briefing-tab-populated.png', {
      ...SNAPSHOT_OPTS,
      animations: 'disabled',
      mask: [page.locator('p.text-xs')],
    })
  })
})
