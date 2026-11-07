// SPDX-License-Identifier: Apache-2.0

// The embeddable widget (widget/embed.js served by the stub) renders the
// model's answer as safe minimal markdown inside its shadow root: hostile
// markup stays text, only http(s) links survive, [n] become chips.
import { expect, test } from "@playwright/test";

import { STUB } from "./helpers";

test("widget renders formatted answers and keeps hostile markup inert", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.dismiss();
  });
  await page.goto(`${STUB}/demo/support.html`);
  await page.getByRole("button", { name: "Open chat" }).click();
  const input = page.getByPlaceholder("Type a message…");
  await input.fill("scenario:widget_xss");
  await input.press("Enter");

  const widget = page.locator("#raggie-widget-root");
  await expect(widget.locator(".m.bot ol li").filter({ hasText: "second" })).toBeVisible();

  const answer = await page.evaluate(() => {
    const root = document.getElementById("raggie-widget-root")!.shadowRoot!;
    const bot = root.querySelector(".m.bot")!;
    const all = Array.from(bot.querySelectorAll("*"));
    return {
      tags: Array.from(new Set(all.map((n) => n.tagName.toLowerCase()))).sort(),
      handlerAttrs: all.flatMap((n) => n.getAttributeNames().filter((a) => a.startsWith("on"))),
      links: Array.from(bot.querySelectorAll("a")).map((a) => ({
        href: a.getAttribute("href"),
        rel: a.getAttribute("rel"),
        target: a.getAttribute("target"),
        text: a.textContent,
      })),
      strong: Array.from(bot.querySelectorAll("strong")).map((n) => n.textContent),
      em: Array.from(bot.querySelectorAll("em")).map((n) => n.textContent),
      code: Array.from(bot.querySelectorAll("code")).map((n) => n.textContent),
      cites: Array.from(bot.querySelectorAll("sup.cite")).map((n) => n.textContent),
      sources: Array.from(bot.querySelectorAll(".srcs li")).map((n) => n.textContent),
      text: bot.textContent,
      xss: (window as unknown as { __xss?: number }).__xss ?? null,
    };
  });

  expect(answer.xss).toBeNull();
  expect(dialogs).toEqual([]);
  expect(answer.tags).toEqual(["a", "code", "div", "em", "li", "ol", "p", "strong", "sup", "ul"]);
  expect(answer.handlerAttrs).toEqual([]);
  expect(answer.links).toEqual([
    { href: "https://example.org/docs", rel: "noopener noreferrer nofollow", target: "_blank", text: "docs" },
  ]);
  expect(answer.strong).toEqual(["Safe"]);
  expect(answer.em).toEqual(["notes"]);
  expect(answer.code).toEqual(["<b>code</b>"]);
  // [1] is a known source; [7] is not and is dropped.
  expect(answer.cites).toEqual(["1"]);
  expect(answer.text).not.toContain("[7]");
  expect(answer.sources).toEqual(['<img src=x onerror="window.__xss=1">']);
  // Markup and entities arrive verbatim as text.
  expect(answer.text).toContain("<script>window.__xss=1</script>");
  expect(answer.text).toContain("&lt;i&gt;");
  expect(answer.text).toContain("click");
});
