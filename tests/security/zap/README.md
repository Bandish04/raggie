# DAST: OWASP ZAP (nightly)

The `dast` job in `.github/workflows/nightly.yml` scans a throwaway e2e stack
(`scripts/e2e-stack.sh`) of its own, so the destructive active scans never touch
the stack the browser e2e suite runs on. It needs Docker and runs in CI only.

## What runs

| Scan | Script | Target | Auth |
|---|---|---|---|
| Baseline (passive, spider + AJAX spider) | `zap-baseline.py` | public origin (Caddy) | none |
| API scan (active) | `zap-api-scan.py` | control plane, from its own `/openapi.json` | admin bearer |
| API scan (active) | `zap-api-scan.py` | edge widget surface, `.zap/edge-public.openapi.json` | widget token + allow-listed `Origin` |

Only that stack runs with `EXPOSE_API_DOCS=true` (for `/openapi.json`), a 2 h
widget-token lifetime and the edge rate limits off, via `E2E_ENV_*`. The
security e2e suite proves the rate limits; an active scan that mostly sees 429s
would prove nothing.

`bootstrap.py` runs after the Playwright `setup` project has onboarded the stack:

1. It logs in as the saved admin.
2. It creates an EXTERNAL workspace whose widget allow-list is the public origin, then gets a widget token for it.
3. It writes the two OpenAPI inputs. The control-plane spec drops `/api/v1/auth/logout` and `/api/v1/auth/change-password`; otherwise the scanner would end its own session halfway and scan the rest unauthenticated.

The tokens are masked in the log and reach the scans through ZAP's
`ZAP_AUTH_HEADER_VALUE` / `ZAP_AUTH_HEADER_SITE`. For the edge scan, ZAP's
replacer adds the `Origin` header to every request.

## What fails the job

`assert_report.py` reads the three JSON reports with `.zap/rules.tsv`. The job fails if:

- any **High** alert appears, unless its rule is `IGNORE`d;
- any alert of a rule marked **`FAIL`** appears, at any risk. These are the curated Medium rules: CSP not set, anti-clickjacking, cookie HttpOnly/SameSite, cross-domain and CORS misconfiguration;
- a report is missing or unreadable (a crashed scan never passes);
- an API scan ran **unauthenticated**: no request carried `Authorization`, or
  none of those got a 2xx. `auth_hook.py` (a ZAP `--hook`) writes this evidence
  from ZAP's message history, because the JSON report has no request headers.

Alerts ZAP itself rates as false positives (confidence 0) are skipped. Unlisted rules only warn. The HTML/JSON reports are uploaded as the `zap-reports` artifact.

## Adding an exception

Add a line to `.zap/rules.tsv`:

```
<plugin id><TAB><IGNORE|WARN|FAIL><TAB><why this is a false positive or accepted>
```

The justification is mandatory, and the line must have exactly three
tab-separated columns (ZAP reads the same file). Prefer `WARN` over `IGNORE`, so
the finding stays visible in the report.

## Tests

```bash
uvx pytest -q -p no:cacheprovider tests/security/zap
```
