// SPDX-License-Identifier: Apache-2.0

import { AxeBuilder } from "@axe-core/playwright";
import { type BrowserContext, type Page, expect, test } from "@playwright/test";

export const STUB = `http://127.0.0.1:${process.env.CHAT_STUB_PORT ?? 58130}`;
export const LOCALES = ["en", "tr"] as const;
export type Locale = (typeof LOCALES)[number];

const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
// Unsigned JWTs with a far-future exp: proxy.ts only checks presence + expiry;
// the stub picks the user from `sub` ("admin" = org super admin).
const token = (sub: string) => `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub, exp: 4102444800 })}.sig`;

export async function signIn(context: BrowserContext, baseURL: string, locale: Locale, sub: "u1" | "admin" | "tzless" | "demo" | null) {
  const cookies: { name: string; value: string; url: string }[] = [{ name: "NEXT_LOCALE", value: locale, url: baseURL }];
  if (sub) cookies.push({ name: "raggie_access", value: token(sub), url: baseURL });
  await context.addCookies(cookies);
}

export async function ask(page: Page, text: string) {
  const box = page.getByRole("textbox", { name: /Ask something|Bir şey sor/ });
  await box.fill(text);
  await box.press("Enter");
}

const BLOCKING = new Set(["serious", "critical"]);

/**
 * axe-core WCAG 2.1 A/AA scan. Serious/critical violations fail the test (soft,
 * so one run reports every page); moderate/minor ones are only summarized.
 */
export async function audit(page: Page, name: string) {
  // Let entrance animations (fade/rise) finish so contrast is measured on the
  // settled page; infinite ones (spinners, pulses) are what users see, so they stay.
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getComputedTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => undefined)),
    ),
  );
  const { violations } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const blocking = violations.filter((v) => BLOCKING.has(v.impact ?? ""));
  const other = violations.filter((v) => !BLOCKING.has(v.impact ?? ""));
  const line = (v: (typeof violations)[number]) =>
    `${v.impact} ${v.id} ×${v.nodes.length}: ${v.nodes
      .slice(0, 3)
      .map((n) => n.target.join(" "))
      .join(" | ")}`;
  console.log(
    `[a11y] ${name}: ${blocking.length} blocking, ${other.length} other` +
      [...blocking, ...other].map((v) => `\n  - ${line(v)}`).join(""),
  );
  if (process.env.A11Y_DUMP) {
    const { writeFileSync, mkdirSync } = await import("node:fs");
    mkdirSync("test-results/a11y", { recursive: true });
    const nodes = violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      nodes: v.nodes.map((n) => ({ target: n.target.join(" "), html: n.html.slice(0, 240), summary: n.failureSummary })),
    }));
    writeFileSync(`test-results/a11y/${name.replace(/\W+/g, "-")}.json`, JSON.stringify(nodes, null, 2));
  }
  test.info().annotations.push({ type: "a11y", description: `${name}: ${blocking.length} blocking, ${other.length} other` });
  expect.soft(blocking.map(line), `${name}: serious/critical axe violations`).toEqual([]);
}
