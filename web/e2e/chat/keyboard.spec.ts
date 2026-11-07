// SPDX-License-Identifier: Apache-2.0

// Keyboard-only smoke: no mouse events. Send a message, open its sources, and
// open the composer tools menu and close it with Escape (focus returns).
import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test("chat is usable with the keyboard alone", async ({ page, context, baseURL }) => {
  await signIn(context, baseURL!, "en", "u1");
  await page.goto("/chat");
  const box = page.getByRole("textbox", { name: "Ask something…" });
  await expect(box).toBeVisible();

  // Reach the composer by tabbing from the top of the page.
  await page.keyboard.press("Tab");
  for (let i = 0; i < 40 && !(await box.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(box).toBeFocused();
  await page.keyboard.type("How much leave do I get?");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Employees get")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Answer ready." })).toHaveCount(1);

  // Sources toggle: focus it and open it with Enter.
  const sources = page.getByRole("button", { name: "Sources · 2" });
  await sources.focus();
  await expect(sources).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(sources).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#src-msg-1-1")).toBeVisible();

  // Composer tools menu: open with Enter, move with arrows, close with Escape.
  const tools = page.getByRole("button", { name: "Add & tools" });
  await tools.focus();
  await page.keyboard.press("Enter");
  const menu = page.getByRole("menu", { name: "Add & tools" });
  await expect(menu).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(tools).toBeFocused();

  // A visible focus indicator on the focused control.
  const outline = await tools.evaluate((el) => {
    const cs = getComputedStyle(el);
    return `${cs.outlineStyle} ${cs.outlineWidth} ${cs.boxShadow}`;
  });
  expect(outline).not.toBe("none 0px none");
});

test("KB document action menu: Escape closes it and focus returns to the trigger", async ({ page, context, baseURL }) => {
  await signIn(context, baseURL!, "en", "admin");
  await page.goto("/admin/knowledge-base");
  const trigger = page.getByRole("button", { name: "Document actions" }).first();
  await expect(trigger).toBeAttached();
  await trigger.focus();
  await page.keyboard.press("Enter");
  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem").first()).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(trigger).toBeFocused();
});
