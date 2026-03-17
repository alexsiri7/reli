import { test, expect, Page } from '@playwright/test'

const MOCK_USER = {
  id: 'user-1',
  email: 'test@example.com',
  name: 'Test User',
}

const MOCK_HISTORY = [
  {
    id: 'msg-1',
    role: 'user' as const,
    content: 'What do I have on my plate today?',
    timestamp: '2026-03-14T09:00:00Z',
  },
  {
    id: 'msg-2',
    role: 'assistant' as const,
    content: 'You have 3 active items: Review the pull request for the auth module, prepare the quarterly report, and schedule the team retrospective.',
    timestamp: '2026-03-14T09:00:05Z',
  },
  {
    id: 'msg-3',
    role: 'user' as const,
    content: 'Can you mark the PR review as done?',
    timestamp: '2026-03-14T09:01:00Z',
  },
  {
    id: 'msg-4',
    role: 'assistant' as const,
    content: 'Done! I\'ve marked "Review pull request for auth module" as complete.',
    timestamp: '2026-03-14T09:01:05Z',
  },
]

async function interceptApi(
  page: Page,
  opts: { history?: boolean } = {}
) {
  await page.route('**/api/auth/me', route =>
    route.fulfill({ json: MOCK_USER, status: 200 })
  )
  await page.route('**/api/things?*', route =>
    route.fulfill({ json: [], status: 200 })
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
    route.fulfill({
      json: { messages_sent: 0, messages_received: 0 },
      status: 200,
    })
  )
  await page.route('**/api/proactive?*', route =>
    route.fulfill({ json: [], status: 200 })
  )
  await page.route('**/api/merge-suggestions', route =>
    route.fulfill({ json: [], status: 200 })
  )
  await page.route('**/api/user-settings', route =>
    route.fulfill({ json: {}, status: 200 })
  )
  await page.route('**/version.json*', route =>
    route.fulfill({ json: { version: '0.0.0' }, status: 200 })
  )
}

async function waitForMobileChat(page: Page) {
  // Wait for the app to render — on mobile the tab bar is visible
  await page.waitForSelector('nav button', { timeout: 20_000 })
  // Switch to chat tab (second nav button)
  await page.locator('nav button').nth(1).click()
  // Disable animations
  await page.addStyleTag({
    content: `*, *::before, *::after {
      animation-duration: 0s !important;
      animation-delay: 0s !important;
      transition-duration: 0s !important;
    }`,
  })
  await page.waitForTimeout(500)
}

const SNAPSHOT_OPTS = { maxDiffPixelRatio: 0.02 }

const MOBILE_VIEWPORTS = [
  { name: 'iphone-se', width: 375, height: 667 },
  { name: 'iphone-14', width: 390, height: 844 },
  { name: 'android', width: 360, height: 800 },
] as const

for (const vp of MOBILE_VIEWPORTS) {
  test.describe(`Mobile chat – ${vp.name} (${vp.width}x${vp.height})`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } })

    test('empty chat — input visible at bottom', async ({ page }) => {
      await interceptApi(page)
      await page.goto('/')
      await waitForMobileChat(page)

      await expect(page).toHaveScreenshot(
        `mobile-chat-empty-${vp.name}.png`,
        { ...SNAPSHOT_OPTS, animations: 'disabled' }
      )

      // Assert the input textarea is visible in the viewport
      const input = page.getByPlaceholder('Message Reli').last()
      await expect(input).toBeVisible()
      const box = await input.boundingBox()
      expect(box).toBeTruthy()
      // Input bottom edge must be above the viewport bottom
      expect(box!.y + box!.height).toBeLessThan(vp.height)
    })

    test('chat with messages — input visible', async ({ page }) => {
      await interceptApi(page, { history: true })
      await page.goto('/')
      await waitForMobileChat(page)
      // Wait for messages to render
      await page
        .waitForSelector('[class*="rounded-2xl"]', { timeout: 5_000 })
        .catch(() => {})
      await page.waitForTimeout(300)

      await expect(page).toHaveScreenshot(
        `mobile-chat-messages-${vp.name}.png`,
        { ...SNAPSHOT_OPTS, animations: 'disabled' }
      )

      // Assert input is still visible
      const input = page.getByPlaceholder('Message Reli').last()
      await expect(input).toBeVisible()
      const box = await input.boundingBox()
      expect(box).toBeTruthy()
      expect(box!.y + box!.height).toBeLessThan(vp.height)
    })

    test('chat with keyboard simulation — input stays visible', async ({ page }) => {
      await interceptApi(page, { history: true })
      await page.goto('/')
      await waitForMobileChat(page)
      await page
        .waitForSelector('[class*="rounded-2xl"]', { timeout: 5_000 })
        .catch(() => {})

      // Simulate mobile keyboard by shrinking the viewport height
      const keyboardHeight = 260
      await page.setViewportSize({
        width: vp.width,
        height: vp.height - keyboardHeight,
      })
      await page.waitForTimeout(300)

      await expect(page).toHaveScreenshot(
        `mobile-chat-keyboard-${vp.name}.png`,
        { ...SNAPSHOT_OPTS, animations: 'disabled' }
      )

      // Input must still be within the now-smaller viewport
      const input = page.getByPlaceholder('Message Reli').last()
      await expect(input).toBeVisible()
      const box = await input.boundingBox()
      expect(box).toBeTruthy()
      expect(box!.y + box!.height).toBeLessThan(vp.height - keyboardHeight)
    })
  })
}
