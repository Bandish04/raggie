# Raggie web

The admin console and internal chat UI for Raggie, built on Next.js (App Router)
with TR/EN i18n via next-intl. The browser only talks to this app. Route
handlers under `app/api/**` and server actions call the control plane (admin
API) and edge (chat/RAG) server-side, attaching the session token from an
httpOnly cookie.

## Develop

Requires Node 22 and pnpm 9. The backend services must be reachable: run
`make up-core` from the repo root, or point the env vars below at a running
stack.

```bash
pnpm install
pnpm dev                     # http://localhost:3000 (slow first compile)
pnpm build && pnpm start     # production build; faster for UI checks
```

The first visit to `/onboarding` creates the initial admin account and asks for
the setup token printed by the installer (also in the control-plane logs).

## Checks

```bash
pnpm lint                    # ESLint
pnpm exec tsc --noEmit       # type check
pnpm test:unit               # node:test unit tests (lib/**/*.test.ts), incl. i18n check
pnpm i18n:check              # messages/*.json: no duplicate keys, identical tr/en key paths
pnpm test:e2e                # Playwright; see playwright.config.ts (E2E_EMAIL / E2E_PASSWORD)
pnpm audit --prod
```

New UI strings go into both `messages/tr.json` and `messages/en.json`. Use ICU
plurals for anything with a count.

## Environment

All variables are read server-side at runtime unless noted otherwise.

| Variable | Default | Purpose |
|---|---|---|
| `CONTROL_PLANE_URL` | `http://localhost:8000` | Control-plane base URL (admin API, auth, onboarding). |
| `EDGE_URL` | `http://localhost:8080` | Edge base URL (chat SSE, conversations). |
| `NEXT_PUBLIC_DEFAULT_LOCALE` | `tr` | UI locale when no `NEXT_LOCALE` cookie is set (`tr` or `en`). |
| `SESSION_TTL_SECONDS` | `28800` | Access-cookie lifetime; keep it at or above the control plane's access-token TTL. |
| `COOKIE_SECURE` | unset | `true`/`false` forces the session cookies' `Secure` flag. When unset, the flag is on only if `RAGGIE_ENV=production`. |
| `RAGGIE_ENV` | unset | `production` makes session cookies HTTPS-only (unless `COOKIE_SECURE=false`). |
| `ENABLE_HSTS` | `false` | `true` adds `Strict-Transport-Security`. Enable only when served over HTTPS. |
| `PUBLIC_WEB_URL` | unset | Comma-separated public origins accepted by the CSRF origin check. Only needed when a reverse proxy rewrites `Host` without sending `X-Forwarded-Host`. |
| `VISION_MODELS`, `LLM_MODEL_PROFILES_JSON` | unset | Same values as edge. Used only to decide whether the chat UI offers image attachments. |

## Security notes

- Mutating `/api/**` handlers are wrapped in `withSameOrigin` (`lib/security/origin.ts`).
  A guard test fails if a new one is not.
- Content-Security-Policy and other headers are set in `next.config.ts`.
  Fonts and icons are self-hosted, so the app makes no third-party requests at
  runtime.
- Access tokens are refreshed single-flight (`lib/auth-refresh.ts`): in `proxy.ts`
  for page loads, and through `getFreshAccessToken()` in route handlers.
- Server-side calls forward `X-Forwarded-For`/`-Proto`
  (`lib/security/forwarded.ts`). In production, put a reverse proxy in front that
  sets `X-Forwarded-For`.

## Third-party assets

- `app/fonts/space-grotesk`, `app/fonts/plus-jakarta-sans`: SIL OFL 1.1 (see the
  `OFL.txt` next to each font). Subset to Latin + Latin Extended.
- `public/fonts/material-symbols-outlined.woff2`: Apache-2.0, Google (see
  `material-symbols-outlined.LICENSE.txt`).
