import { expect, test, type Page } from "@playwright/test";

import { childrenOf, CHILD_ID, history, PREFERENCE_ID, session, thingDetail, topLevel, userModel } from "./fixtures";

const NOT_SIGNED_IN = { status: 401, json: { detail: "Not signed in: sign in with Google at /." } };

/** Answer every `/api` request from the fixtures, so these tests need no backend and no database. */
async function stubApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/auth/me") {
      await route.fulfill({ json: session });
      return;
    }
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

test.describe("Views", () => {
  test.beforeEach(async ({ page }) => {
    await stubApi(page);
  });

  test("the tree expands a node", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: "Rebuild Reli" })).toBeVisible();
    expect(await page.locator("main").getByRole("button").count()).toBe(1);

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

  test("a urls entry outside http(s) is shown as text, not as a link", async ({ page }) => {
    const tainted = {
      ...thingDetail,
      thing: {
        ...thingDetail.thing,
        urls: { ...thingDetail.thing.urls, danger: "javascript:alert(1)", scheme_relative: "//evil.test/" },
      },
    };
    await page.route(`**/api/things/${CHILD_ID}`, (route) => route.fulfill({ json: tainted }));
    await page.goto(`/things/${CHILD_ID}`);

    await expect(page.getByRole("link", { name: "https://github.com/alexsiri7/reli/issues/1414" })).toBeVisible();
    await expect(page.getByText("javascript:alert(1)")).toBeVisible();
    await expect(page.getByRole("link", { name: "javascript:alert(1)" })).toHaveCount(0);
    await expect(page.getByText("//evil.test/")).toBeVisible();
    await expect(page.getByRole("link", { name: "//evil.test/" })).toHaveCount(0);
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

  // --- Session ---------------------------------------------------------------

  test("a visitor without a session is offered Google sign-in and nothing else", async ({ page }) => {
    await page.route("**/api/auth/me", (route) => route.fulfill(NOT_SIGNED_IN));
    await page.goto("/");

    await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Rebuild Reli" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Tree" })).toHaveCount(0);
    await expect(page).toHaveScreenshot("sign-in.png", { fullPage: true });
  });

  test("the sign-in button goes where /api/auth/google points", async ({ page }) => {
    await page.route("**/api/auth/me", (route) => route.fulfill(NOT_SIGNED_IN));
    await page.route("**/api/auth/google", (route) =>
      route.fulfill({ json: { auth_url: "https://accounts.google.com/o/oauth2/v2/auth?state=stubbed" } }),
    );
    await page.route("https://accounts.google.com/**", (route) =>
      route.fulfill({ contentType: "text/html", body: "<title>Google</title>" }),
    );
    await page.goto("/");

    await page.getByRole("button", { name: "Sign in with Google" }).click();

    await expect(page).toHaveURL(/accounts\.google\.com/);
  });

  test("a deploy without the sign-in configured says which settings a human sets", async ({ page }) => {
    const detail = "Google sign-in is not configured on this deploy: a human sets SECRET_KEY (CLAUDE.md, Google sign-in).";
    await page.route("**/api/auth/me", (route) => route.fulfill(NOT_SIGNED_IN));
    await page.route("**/api/auth/google", (route) => route.fulfill({ status: 501, json: { detail } }));
    await page.goto("/");

    await page.getByRole("button", { name: "Sign in with Google" }).click();

    await expect(page.getByText(detail)).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeEnabled();
  });

  test("an account outside the allowlist is told the view is invite-only", async ({ page }) => {
    await page.route("**/api/auth/me", (route) => route.fulfill(NOT_SIGNED_IN));
    await page.goto("/?error=invite_only");

    await expect(page.getByText("This Reli is invite-only")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();
  });

  test("an unknown error code shows a fixed sentence, never the code itself", async ({ page }) => {
    await page.route("**/api/auth/me", (route) => route.fulfill(NOT_SIGNED_IN));
    await page.goto("/?error=" + encodeURIComponent("Your account is locked: call +1 555 0100"));

    await expect(page.getByText("Sign-in did not complete.", { exact: true })).toBeVisible();
    await expect(page.getByText("Your account is locked")).toHaveCount(0);
  });

  for (const code of ["__proto__", "toString"]) {
    test(`the inherited object member ${code} is an unknown error code too`, async ({ page }) => {
      await page.route("**/api/auth/me", (route) => route.fulfill(NOT_SIGNED_IN));
      await page.goto(`/?error=${code}`);

      await expect(page.getByText("Sign-in did not complete.", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();
    });
  }

  test("a 401 mid-session falls back to the sign-in view", async ({ page }) => {
    await page.route("**/api/things", (route) => route.fulfill(NOT_SIGNED_IN));
    await page.goto("/");

    await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();
  });

  test("signing out posts to the logout route and returns to the sign-in view", async ({ page }) => {
    let signedOut = false;
    await page.route("**/api/auth/logout", async (route) => {
      expect(route.request().method()).toBe("POST");
      signedOut = true;
      await route.fulfill({ status: 204 });
    });
    await page.goto("/");
    await expect(page.getByText(session.email)).toBeVisible();

    await page.getByRole("button", { name: "Sign out" }).click();

    await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();
    expect(signedOut).toBe(true);
  });

  // --- Errors and empty states ------------------------------------------------

  test("a server error on the tree shows the error and not the sign-in view", async ({ page }) => {
    await page.route("**/api/things", (route) => route.fulfill({ status: 500, json: { detail: "boom" } }));
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Tree" })).toBeVisible();
    await expect(page.getByText(/Could not load: .*500/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign in with Google" })).toHaveCount(0);
    await expect(page.locator(".tree")).toHaveCount(0);
  });

  test("a non-JSON upstream error at sign-in falls back to the bare status", async ({ page }) => {
    await page.route("**/api/auth/me", (route) => route.fulfill(NOT_SIGNED_IN));
    await page.route("**/api/auth/google", (route) =>
      route.fulfill({ status: 502, contentType: "text/html", body: "<html><body>Bad Gateway</body></html>" }),
    );
    await page.goto("/");

    await page.getByRole("button", { name: "Sign in with Google" }).click();

    await expect(page.locator(".status.error").getByText(/502/)).toBeVisible();
    await expect(page.getByText("<html")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeEnabled();
  });

  test("a refused reject keeps the card and says why", async ({ page }) => {
    await page.route(`**/api/preferences/${PREFERENCE_ID}/reject`, (route) =>
      route.fulfill({ status: 403, json: { detail: "cross-origin" } }),
    );
    await page.goto("/user-model");

    await page.getByRole("button", { name: "Reject this preference" }).click();

    await expect(page.getByText(/Could not reject: .*403/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Reject this preference" })).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Reject this preference" })).toBeEnabled();
    await expect(page.getByText("Rejected")).toHaveCount(1);
  });

  test("a history failure leaves the Thing readable", async ({ page }) => {
    await page.route(`**/api/things/${CHILD_ID}/history`, (route) => route.fulfill({ status: 500 }));
    await page.goto(`/things/${CHILD_ID}`);

    await expect(page.getByRole("heading", { name: "Read-only web view", level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Relationships" })).toBeVisible();
    await expect(page.getByText(/Could not load: .*500/)).toHaveCount(1);
    await expect(page.getByRole("heading", { name: "History" })).toHaveCount(0);
  });

  test("a failed session probe is an error, not a sign-out", async ({ page }) => {
    await page.route("**/api/auth/me", (route) => route.fulfill({ status: 500 }));
    await page.goto("/");

    await expect(page.getByText(/Could not load: .*500/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign in with Google" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Rebuild Reli" })).toHaveCount(0);
  });

  test("a failed sign-out keeps the session", async ({ page }) => {
    await page.route("**/api/auth/logout", (route) => route.fulfill({ status: 500 }));
    await page.goto("/");
    await expect(page.getByText(session.email)).toBeVisible();

    await page.getByRole("button", { name: "Sign out" }).click();

    await expect(page.locator("main .status.error").getByText(/500/)).toBeVisible();
    await expect(page.getByText(session.email)).toBeVisible();
    await expect(page.getByRole("link", { name: "Rebuild Reli" })).toBeVisible();
  });

  test("an empty tree says so", async ({ page }) => {
    await page.route("**/api/things", (route) => route.fulfill({ json: { things: [] } }));
    await page.goto("/");

    await expect(page.getByText("Nothing here yet.")).toBeVisible();
    await expect(page.locator(".tree")).toHaveCount(0);
  });

  test("an empty user model says so", async ({ page }) => {
    await page.route("**/api/user-model", (route) => route.fulfill({ json: { scope: null, preferences: [] } }));
    await page.goto("/user-model");

    await expect(page.getByText("No preferences recorded yet.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Reject this preference" })).toHaveCount(0);
  });

  test("a truncated history announces the cut", async ({ page }) => {
    const truncated = { ...history, truncated: true, total: 250 };
    await page.route(`**/api/things/${CHILD_ID}/history`, (route) => route.fulfill({ json: truncated }));
    await page.goto(`/things/${CHILD_ID}`);

    await expect(page.getByText("Showing the newest 3 of 250 entries.")).toBeVisible();
    await expect(page.locator(".history table tbody tr")).toHaveCount(3);
  });

  test("an unknown path redirects to the tree", async ({ page }) => {
    await page.goto("/nowhere/at/all");

    await expect(page).toHaveURL("/");
    await expect(page.getByRole("link", { name: "Rebuild Reli" })).toBeVisible();
  });
});
