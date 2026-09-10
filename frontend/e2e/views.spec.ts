import { expect, test, type Page } from "@playwright/test";

import { childrenOf, CHILD_ID, history, thingDetail, topLevel, userModel } from "./fixtures";

/** Answer every `/api` request from the fixtures, so these tests need no backend and no database. */
async function stubApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/things") {
      const parent = url.searchParams.get("parent");
      await route.fulfill({ json: parent === null ? topLevel : (childrenOf[parent] ?? { things: [] }) });
      return;
    }
    if (url.pathname === `/api/things/${CHILD_ID}`) {
      await route.fulfill({ json: thingDetail });
      return;
    }
    if (url.pathname === `/api/things/${CHILD_ID}/history`) {
      await route.fulfill({ json: history });
      return;
    }
    if (url.pathname === "/api/user-model") {
      await route.fulfill({ json: userModel });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: `not stubbed: ${url.pathname}` } });
  });
}

test.beforeEach(async ({ page }) => {
  await stubApi(page);
});

test("the tree expands a node", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Rebuild Reli" })).toBeVisible();
  expect(await page.getByRole("button").count()).toBe(1);

  await page.getByRole("button", { name: "Expand" }).click();

  await expect(page.getByRole("link", { name: "Read-only web view" })).toBeVisible();
  await expect(page).toHaveScreenshot("tree-expanded.png", { fullPage: true });
});

test("a leaf offers no expansion", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("link", { name: "Book the dentist" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Expand" })).toHaveCount(1);
});

test("thing detail shows notes, relationships and the journal", async ({ page }) => {
  await page.goto(`/things/${CHILD_ID}`);

  await expect(page.getByRole("heading", { name: "Read-only web view", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Parent" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "claude_scheduled" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "user", exact: true })).toBeVisible();
  await expect(page).toHaveScreenshot("thing-detail.png", { fullPage: true });
});

test("the user model shows evidence inline and marks a rejected preference", async ({ page }) => {
  await page.goto("/user-model");

  await expect(page.getByRole("link", { name: "Prefers deep work 9-11am" })).toBeVisible();
  await expect(page.getByText("Rejected")).toBeVisible();
  // One reject button: the rejected card has none, so the only one belongs to the live preference.
  await expect(page.getByRole("button", { name: "Reject this preference" })).toHaveCount(1);
  await expect(page.getByRole("link", { name: "Moved the 9am standup again" }).first()).toBeVisible();
  await expect(page).toHaveScreenshot("user-model.png", { fullPage: true });
});

test("rejecting a preference replaces the card with what the endpoint returned", async ({ page }) => {
  const rejected = {
    ...userModel.preferences[0]!,
    rejected: true,
    thing: { ...userModel.preferences[0]!.thing, tags: ["#Preference", "#Rejected"] },
  };
  await page.route(`**/api/preferences/${rejected.thing.id}/reject`, async (route) => {
    expect(route.request().method()).toBe("POST");
    await route.fulfill({ json: rejected });
  });
  await page.goto("/user-model");

  await page.getByRole("button", { name: "Reject this preference" }).click();

  await expect(page.getByRole("button", { name: "Reject this preference" })).toHaveCount(0);
  await expect(page.getByText("Rejected")).toHaveCount(2);
});

test("the tree is reachable from the user model in one click from evidence", async ({ page }) => {
  await page.goto("/user-model");

  await page.getByRole("link", { name: "Read-only web view" }).click();

  await expect(page.getByRole("heading", { name: "Read-only web view", level: 1 })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(`/things/${CHILD_ID}`);
});
