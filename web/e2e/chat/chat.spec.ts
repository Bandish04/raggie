// SPDX-License-Identifier: Apache-2.0

// Characterization of the chat client (components/chat/*): what it renders for
// every SSE event the edge sends and what it puts in the request body. Runs the
// production build against e2e/chat/stub-server.mjs (see playwright.chat.config.ts).
import { expect, test as base, type Page } from "@playwright/test";

const STUB = `http://127.0.0.1:${process.env.CHAT_STUB_PORT ?? 58130}`;

type ChatRequest = {
  body: Record<string, unknown>;
  idempotencyKey: string | null;
  acceptLanguage: string | null;
};

async function chatRequests(): Promise<ChatRequest[]> {
  return (await (await fetch(`${STUB}/__requests`)).json()) as ChatRequest[];
}

const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
// An unsigned JWT with a future exp: proxy.ts only checks presence + expiry.
const ACCESS = `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "u1", exp: 4102444800 })}.sig`;

const test = base.extend<{ chat: Page }>({
  chat: async ({ page, context, baseURL }, provide) => {
    await fetch(`${STUB}/__requests`, { method: "DELETE" });
    await context.addCookies([
      { name: "raggie_access", value: ACCESS, url: baseURL! },
      { name: "NEXT_LOCALE", value: "en", url: baseURL! },
    ]);
    await page.goto("/chat");
    await expect(page.getByPlaceholder("Ask something…")).toBeVisible();
    await provide(page);
  },
});

async function ask(page: Page, text: string) {
  const box = page.getByPlaceholder("Ask something…");
  await box.fill(text);
  await box.press("Enter");
}

// The assistant bubble's actions only render after the stream ends.
async function waitForAnswerDone(page: Page) {
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
}

async function openToolsMenu(page: Page) {
  await page.getByRole("button", { name: "Add & tools" }).click();
  return page.getByRole("menu", { name: "Add & tools" });
}

test("full turn: request body, reasoning, tools, answer markdown, citations and sources", async ({ chat }) => {
  await ask(chat, "How much leave do I get?");
  await expect(chat.getByText("Employees get")).toBeVisible();
  await waitForAnswerDone(chat);

  const [req] = await chatRequests();
  expect(req.idempotencyKey).toMatch(/\S{8,}/);
  expect(req.acceptLanguage).toBe("en");
  expect(req.body).toEqual({
    workspace_id: "ws-1",
    message: "How much leave do I get?",
    history: [],
    web_search: false,
    model: "model-a",
    answer_style: "balanced",
    reasoning_effort: "medium",
    attachments: [],
    locale: "en",
  });

  // The user turn and the answer body (markdown rendered).
  await expect(chat.getByText("How much leave do I get?", { exact: true })).toBeVisible();
  await expect(chat.locator("strong", { hasText: "20 days" })).toBeVisible();
  // Reasoning and tool steps collapse into disclosures once the answer streams.
  await expect(chat.getByRole("button", { name: /Reasoning/ })).toBeVisible();
  await expect(chat.getByRole("button", { name: /Tools used · 1/ })).toBeVisible();

  // [n] markers become links to their source card.
  await expect(chat.getByRole("link", { name: "1", exact: true })).toHaveAttribute("href", "#src-msg-1-1");
  await expect(chat.getByRole("link", { name: "2", exact: true })).toHaveAttribute("href", "#src-msg-1-2");

  // Sources: a collapsed "Sources · 2" toggle → a doc card and a web card.
  const toggle = chat.getByRole("button", { name: "Sources · 2" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  const doc = chat.locator("#src-msg-1-1");
  await expect(doc).toContainText("Employee handbook");
  await expect(doc).toContainText("91%");
  await doc.getByRole("button").click();
  await expect(doc).toContainText("Employees get 20 days of annual leave.");
  const web = chat.locator("#src-msg-1-2");
  await expect(web).toHaveAttribute("href", "https://www.example.org/leave-policy");
  await expect(web).toContainText("Leave policy explained");
  await expect(web).toContainText("example.org");
  await expect(web).toContainText("read · annual leave policy");

  // Answer actions: copy, feedback (message id known), regenerate (last turn).
  await expect(chat.getByRole("button", { name: "Copy" }).first()).toBeVisible();
  await expect(chat.getByRole("button", { name: "Regenerate" })).toBeVisible();

  // A follow-up turn carries the conversation id and no client history.
  await ask(chat, "And sick leave?");
  await waitForAnswerDone(chat);
  const second = (await chatRequests())[1];
  expect(second.body.conversation_id).toBe("conv-1");
  expect(second.body.history).toEqual([]);
});

test("deep research: request flags, staged progress line and query recap", async ({ chat }) => {
  const menu = await openToolsMenu(chat);
  await menu.getByRole("menuitemcheckbox", { name: "Deep research" }).click();
  await chat.keyboard.press("Escape");
  await expect(chat.getByText("Deep research", { exact: true })).toBeVisible();

  await ask(chat, "scenario:deep compare leave rules");
  await expect(chat.getByText("Reading public pages...")).toBeVisible();
  await expect(chat.getByText("leave policy 2026")).toBeVisible();
  await expect(chat.getByText("Deep answer")).toBeVisible();
  await waitForAnswerDone(chat);
  await expect(chat.getByText("Reading public pages...")).toHaveCount(0);

  const [req] = await chatRequests();
  expect(req.body.web_search).toBe(true);
  expect(req.body.deep_search).toBe(true);
});

test("web mode and model picker change the request body", async ({ chat }) => {
  const menu = await openToolsMenu(chat);
  await menu.getByRole("menuitemcheckbox", { name: "Web search" }).click();
  await chat.keyboard.press("Escape");
  await chat.getByRole("button", { name: "AI model" }).click();
  await chat.getByRole("option", { name: /model-b/ }).click();

  await ask(chat, "anything new?");
  await waitForAnswerDone(chat);
  const [req] = await chatRequests();
  expect(req.body.web_search).toBe(true);
  expect(req.body.deep_search).toBeUndefined();
  expect(req.body.model).toBe("model-b");
});

test("image attachment is sent as a data URL", async ({ chat }) => {
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "base64",
  );
  await chat.locator('input[type="file"]').setInputFiles({ name: "dot.png", mimeType: "image/png", buffer: png });
  await expect(chat.getByRole("button", { name: "Remove image" })).toBeVisible();
  await ask(chat, "what is in the picture?");
  await waitForAnswerDone(chat);
  const [req] = await chatRequests();
  const attachments = req.body.attachments as { type: string; mime: string; data_url: string }[];
  expect(attachments).toHaveLength(1);
  expect(attachments[0].type).toBe("image");
  expect(attachments[0].mime).toBe("image/png");
  expect(attachments[0].data_url.startsWith("data:image/png;base64,")).toBe(true);
});

test("mid-stream error keeps the partial answer and shows the localized message", async ({ chat }) => {
  await ask(chat, "scenario:midstream_error boom");
  await expect(chat.getByText("The language model didn't respond. Please try again.")).toBeVisible();
  await expect(chat.getByText("Partial")).toBeVisible();
  await expect(chat.getByRole("button", { name: "Try again" })).toBeVisible();
});

test("an unknown error code falls back to the edge's own message", async ({ chat }) => {
  await ask(chat, "scenario:unknown_error boom");
  await expect(chat.getByText("Edge says no.")).toBeVisible();
});

test("pre-stream 429 shows the rate-limit message with the Retry-After hint", async ({ chat }) => {
  await ask(chat, "scenario:rate_limited quick");
  await expect(
    chat.getByText(
      "You're sending messages too quickly. Please wait a moment and try again. Try again in 7 seconds.",
    ),
  ).toBeVisible();
  expect(await chatRequests()).toHaveLength(1);
});

test("markdown images: external URLs never render as <img>, same-origin ones do", async ({ chat }) => {
  await ask(chat, "scenario:image show");
  await waitForAnswerDone(chat);
  await expect(chat.locator('img[src*="evil.example"]')).toHaveCount(0);
  await expect(chat.getByRole("link", { name: "leak" })).toHaveAttribute(
    "href",
    "https://evil.example/pixel.png?d=secret",
  );
  await expect(chat.locator('img[src="/icon.svg"]')).toHaveCount(1);
});

test("web offer: the hint appears and its button re-asks as a web turn", async ({ chat }) => {
  await ask(chat, "scenario:web_offer what is new?");
  await waitForAnswerDone(chat);
  await expect(chat.getByText(/Your documents don't clearly answer this/)).toBeVisible();
  await chat.getByRole("button", { name: "Search the web" }).click();
  await waitForAnswerDone(chat);
  const reqs = await chatRequests();
  expect(reqs).toHaveLength(2);
  expect(reqs[1].body.message).toBe("scenario:web_offer what is new?");
  expect(reqs[1].body.web_search).toBe(true);
});

test("web unavailable shows the calm documents-only note", async ({ chat }) => {
  await ask(chat, "scenario:web_unavailable hi");
  await waitForAnswerDone(chat);
  await expect(chat.getByText(/Web search is currently unavailable/)).toBeVisible();
  await expect(chat.getByText("From documents only.")).toBeVisible();
});

test("reconnect: the turn is resumed by message id and the fresh answer replaces the partial", async ({ chat }) => {
  await ask(chat, "scenario:reconnect long answer");
  await expect(chat.getByText("Fresh resumed answer.")).toBeVisible();
  await waitForAnswerDone(chat);
  await expect(chat.getByText("Partial before drain")).toHaveCount(0);
  const reqs = await chatRequests();
  expect(reqs).toHaveLength(2);
  expect(reqs[1].body).toEqual({
    workspace_id: "ws-1",
    conversation_id: "conv-8",
    resume_message_id: "msg-8",
    locale: "en",
  });
  expect(reqs[1].idempotencyKey).not.toBe(reqs[0].idempotencyKey);
});

test("stop aborts the stream silently and keeps the partial answer", async ({ chat }) => {
  await ask(chat, "scenario:slow tell me everything");
  await expect(chat.getByText(/tok2/)).toBeVisible();
  await chat.getByRole("button", { name: "Stop" }).click();
  await waitForAnswerDone(chat);
  const answer = chat.getByText(/tok0/);
  const frozen = await answer.textContent();
  await chat.waitForTimeout(1000);
  expect(await answer.textContent()).toBe(frozen);
  expect(frozen).not.toContain("tok59");
  await expect(chat.getByText("I couldn't generate your answer right now. Please try again.")).toHaveCount(0);
});
