# Security Policy

Raggie stores internal documents, chat history and credentials for the
services it talks to. We treat security reports as our highest-priority work
and we are grateful to everyone who reports issues responsibly.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes — security fixes are released as 0.1.x patch versions |
| `main` | Best effort — fixes land here first, but `main` is not a release |
| < 0.1.0 | No |

## Reporting a vulnerability

**Please do not open a public issue, discussion or pull request for a
security problem.**

Report it privately through one of these channels:

1. **GitHub private vulnerability reporting (preferred):**
   <https://github.com/alicangunduz/raggie/security/advisories/new>
2. **Email:** [hi@alicangunduz.dev](mailto:hi@alicangunduz.dev) with `[raggie security]`
   in the subject. Do not include exploit details in public issues.

Please include:

- the affected component (for example `services/edge`, `services/control-plane`,
  `web`, `widget/embed.js`, `deploy/`) and the version or commit;
- your deployment shape (install.sh, docker compose from source, Kubernetes)
  and any non-default settings that matter;
- the prerequisites an attacker needs (anonymous, widget visitor, STAFF,
  WORKSPACE_ADMIN, SUPER_ADMIN, network position);
- the impact you observed or expect;
- step-by-step reproduction, ideally with a minimal proof of concept;
- a suggested fix or mitigation, if you have one.

Do not include real customer data, real secrets or other people's documents in
your report. Use the deterministic mock LLM and synthetic data where you can.

## What happens next

| Step | Target |
|---|---|
| Acknowledge your report | within 3 business days |
| Initial assessment (validity, severity, affected versions) | within 10 business days |
| Fix for critical / high severity | as fast as possible, target 30 days |
| Fix for medium severity | target 60 days |
| Fix for low severity | next regular release |

We keep you updated as we work on the issue, credit you in the advisory and
release notes (unless you prefer to stay anonymous), and request a CVE through
GitHub Security Advisories when appropriate.

## Coordinated disclosure

We follow a **90-day** coordinated disclosure window, counted from your
initial report:

- If a fix ships earlier, we publish the advisory together with the fix and you
  are free to discuss the issue afterwards.
- If we need more time for a complex fix, we will ask; extensions are agreed
  with you, not imposed.
- If an issue is being actively exploited, we may publish mitigations sooner.

## Scope

**In scope**

- `services/` — edge (Go), control plane (FastAPI), workers, embeddings gateway
- `web/` — admin console and internal chat
- `widget/` — the embeddable widget loader
- `deploy/` — the shipped Docker Compose and Kubernetes manifests and the
  installer (`web/public/install.sh`)

Examples of what we especially want to hear about: authentication or session
bypass, privilege escalation between roles, cross-organization or
cross-workspace data access, widget tokens reaching admin APIs, SSRF, injection,
unsafe file parsing, and secret exposure.

**Out of scope**

- Vulnerabilities in third-party dependencies that are not exploitable through
  Raggie — please report those upstream (tell us too if Raggie is affected).
- Deployments that ignore documented settings, for example running with
  `RAGGIE_ENV=development`, default or example secrets, or datastore ports
  exposed to the internet.
- Volumetric denial of service (flooding with traffic).
- Missing hardening that is already documented as a known gap in
  [docs/security-model.md](docs/security-model.md), unless you show a concrete
  exploit path beyond what is documented.
- Findings from automated scanners without a demonstrated impact.
- Social engineering of maintainers or users, and physical attacks.

## Safe harbor

We will not pursue or support legal action against you for security research
that:

- is done in good faith and stays within the scope above;
- uses only your own installation or test data you are allowed to use;
- avoids privacy violations, data destruction and service degradation;
- gives us reasonable time to fix the issue before public disclosure.

If in doubt, ask us first through a private report.

## How we test

These checks run in CI or are part of the test suites:

- **Authorization matrix tests** for every HTTP route in the edge
  (`services/edge/internal/httpserver/authz_matrix_test.go`) and the control
  plane (`services/control-plane/tests/security/test_authz_matrix.py`). They fail
  when a route has no access policy, and check that every principal not allowed
  on a route is refused.
- **Tenant isolation tests** for cross-organization access in the control plane,
  and a widget isolation test that a widget token is refused by admin APIs.
- **Fuzzing:** Go fuzz targets for request decoding, LLM stream parsing, MCP
  tool handling, the web-fetch SSRF guard, client IP parsing and widget token
  parsing (`make fuzz-short` runs each briefly in CI), plus property-based
  tests for filename handling and document parsing.
- **Scanners:** gitleaks, semgrep, bandit, gosec, govulncheck, pip-audit,
  `pnpm audit`, trivy (configuration) and hadolint.

The threat model, trust boundaries and known gaps are documented in
[docs/security-model.md](docs/security-model.md).
