// SPDX-License-Identifier: Apache-2.0

// Regenerates the README visuals in docs/assets/ from the real UI (production
// build) against the stub backend with demo data (readme-fixtures.mjs). Skipped
// in normal runs; use `pnpm capture:readme`.
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync, statSync } from "node:fs";
import path from "node:path";

import { type Browser, type Page, expect, test } from "@playwright/test";

import { STUB, ask, signIn } from "./helpers";
import { README_QUESTIONS } from "./readme-fixtures.mjs";

test.skip(!process.env.CAPTURE_README, "set CAPTURE_README=1 (pnpm capture:readme) to regenerate docs/assets");
test.describe.configure({ mode: "serial" });

const ASSETS = path.resolve(__dirname, "../../../docs/assets");
const VIEWPORT = { width: 1440, height: 900 };

test.beforeAll(() => mkdirSync(ASSETS, { recursive: true }));

async function demoPage(browser: Browser, baseURL: string, locale: "en" | "tr", video?: string) {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    colorScheme: "light",
    reducedMotion: "no-preference",
    ...(video ? { recordVideo: { dir: video, size: VIEWPORT } } : {}),
  });
  await signIn(context, baseURL, locale, "demo");
  return { context, page: await context.newPage() };
}

async function answerWithSources(page: Page, question: string, sourcesLabel: string) {
  await page.goto("/chat");
  await ask(page, question);
  const sources = page.getByRole("button", { name: `${sourcesLabel} · 2` });
  await expect(sources).toBeVisible();
  await expect(page.getByRole("button", { name: /Send|Gönder/ })).toBeVisible();
  await sources.click();
  await page.locator('[id$="-1"][id^="src-"]').getByRole("button").first().click();
  await page.mouse.move(0, 0);
}

test("chat answer with citations and sources (en, tr)", async ({ browser, baseURL }) => {
  for (const [locale, label] of [
    ["en", "Sources"],
    ["tr", "Kaynaklar"],
  ] as const) {
    const { context, page } = await demoPage(browser, baseURL!, locale);
    await answerWithSources(page, README_QUESTIONS[locale], label);
    await page.screenshot({ path: path.join(ASSETS, `chat-answer-sources-${locale}.png`) });
    await context.close();
  }
});

test("knowledge base grid with a failed document", async ({ browser, baseURL }) => {
  const { context, page } = await demoPage(browser, baseURL!, "en");
  // A little taller than the other shots so the item-count line under the
  // grid is in frame instead of cut at the bottom edge.
  await page.setViewportSize({ width: VIEWPORT.width, height: 960 });
  await page.goto("/admin/knowledge-base");
  await expect(page.getByTestId("doc-failure")).toContainText("Processing took longer than 120 seconds");
  await expect(page.getByText("6 folders · 6 documents")).toBeInViewport({ ratio: 1 });
  await page.mouse.move(0, 0);
  await page.screenshot({ path: path.join(ASSETS, "knowledge-base-en.png") });
  await context.close();
});

test("admin AI page with the embeddings card", async ({ browser, baseURL }) => {
  const { context, page } = await demoPage(browser, baseURL!, "en");
  await page.goto("/admin/ai");
  const card = page.locator(".card").filter({ has: page.getByRole("heading", { name: "Embeddings & reranker" }) });
  await expect(card.getByText("Document text stays on this server.")).toBeVisible();
  await card.evaluate((el) => el.scrollIntoView({ block: "center" }));
  await page.mouse.move(0, 0);
  await page.screenshot({ path: path.join(ASSETS, "admin-embeddings-en.png") });
  await context.close();
});

test("widget embedded on a customer page", async ({ browser }) => {
  const context = await browser.newContext({ viewport: VIEWPORT, colorScheme: "light" });
  const page = await context.newPage();
  await page.goto(`${STUB}/demo/support.html`);
  await page.getByRole("button", { name: "Open chat" }).click();
  const input = page.getByPlaceholder("Type a message…");
  await input.fill(README_QUESTIONS.widget);
  await input.press("Enter");
  await expect(page.locator("#raggie-widget-root").getByText("15 minutes")).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(ASSETS, "widget-embedded-en.png") });
  await context.close();
});

test("hero clip: question → streamed answer with citations → sources", async ({ browser, baseURL }) => {
  const dir = path.join(test.info().outputDir, "video");
  const { context, page } = await demoPage(browser, baseURL!, "en", dir);
  await page.goto("/chat");
  const box = page.getByRole("textbox", { name: "Ask something…" });
  await expect(box).toBeVisible();
  await page.waitForTimeout(800);
  await box.click();
  await page.keyboard.type(README_QUESTIONS.en, { delay: 35 });
  await page.waitForTimeout(300);
  await page.keyboard.press("Enter");
  const sources = page.getByRole("button", { name: "Sources · 2" });
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(900);
  await sources.click();
  await page.waitForTimeout(700);
  await page.locator("#src-msg-readme-en-1").getByRole("button").first().click();
  await page.waitForTimeout(3600);
  const video = page.video();
  await context.close();
  const webm = path.join(ASSETS, "hero.webm");
  await video!.saveAs(webm);
  rmSync(dir, { recursive: true, force: true });

  // MP4 + GIF need ffmpeg; without it only the webm is written.
  let ffmpeg = true;
  try {
    execFileSync("ffmpeg", ["-version"], { stdio: "ignore" });
  } catch {
    ffmpeg = false;
  }
  test.info().annotations.push({ type: "ffmpeg", description: ffmpeg ? "available" : "missing: webm only" });
  if (!ffmpeg) return;
  const mp4 = path.join(ASSETS, "hero.mp4");
  const gif = path.join(ASSETS, "hero.gif");
  // Trim the page load, keep 1440×900 for the mp4, 960 px wide at 10 fps for the gif.
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-ss", "0.6", "-i", webm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28", "-preset", "slow", "-movflags", "+faststart", "-an", mp4]);
  execFileSync("ffmpeg", [
    "-y", "-loglevel", "error", "-ss", "0.6", "-i", webm,
    "-vf", "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
    gif,
  ]);
  for (const f of [webm, mp4, gif]) {
    expect(existsSync(f)).toBe(true);
  }
  expect(statSync(gif).size).toBeLessThan(4 * 1024 * 1024);
});
