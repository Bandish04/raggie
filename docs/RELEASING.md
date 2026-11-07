# Releasing

How a maintainer cuts a Raggie release. A release is a signed `vX.Y.Z` tag on
`main`; [`release.yml`](../.github/workflows/release.yml) builds and publishes
everything from it.

## 1. Freeze and preflight

On an up-to-date `main` with the release changes merged:

```bash
scripts/release-preflight.sh 0.1.0
```

It is read-only, needs no Docker or network, and takes a few seconds. It prints
a PASS/WARN/FAIL table and exits 1 on any FAIL:

| Check | Fails when |
|---|---|
| `changelog` | `CHANGELOG.md` has no dated, non-empty `## [X.Y.Z] - YYYY-MM-DD` section, as extracted by the same awk program `release.yml` uses for the notes |
| `git` | the working tree is not clean, or the `vX.Y.Z` tag already exists on another commit |
| `i18n` | a `web/messages/*.json` catalog has missing, extra or duplicate keys compared with `en.json` (`pnpm i18n:check` when `web/node_modules` exists) |
| `config-docs` | `docs/configuration.md` is stale (`scripts/gen-config-docs.py --check`) |
| `spdx` | a source file lacks its SPDX header (`scripts/license/spdx.py --check`) |
| `notices` | `THIRD_PARTY_NOTICES.md` has an unapproved "Review required" row (`scripts/notices/check_review.py`); a WARN when it lists `darwin`/`win32` packages, i.e. it was generated on macOS or Windows |
| `forbidden` | a shippable file (tracked, or untracked and not ignored) matches a rule in [`scripts/release/forbidden.txt`](../scripts/release/forbidden.txt): private deployment details, contact-address and date placeholders, developer paths, private files. Each rule carries its reason |
| `gitleaks` | gitleaks finds a secret anywhere in the history (a WARN when gitleaks is not installed; CI scans every push) |
| `images` | a compose, Helm or Kubernetes image is `:latest` or has no tag (a WARN for images without a digest). Images built from this repository (`raggie/*`) are exempt |
| `installer` | `web/public/install.sh` lost the `RAGGIE_DEFAULT_VERSION="…"` line that `release.yml` pins |

`--only changelog,git` runs a subset. The preflight is deliberately not part of
per-PR CI: some rules (the contact-address placeholders) are expected to fail
until the release itself.

## 2. Tag

```bash
git switch main && git pull --ff-only
scripts/release-preflight.sh 0.1.0          # again, on exactly what you tag
git tag -s v0.1.0 -m "Raggie 0.1.0"
git push origin v0.1.0
```

A tag with a suffix (`v0.2.0-rc.1`) becomes a pre-release.

## 3. What `release.yml` produces

On the tag push it:

1. regenerates `THIRD_PARTY_NOTICES.md` on Linux and fails on unapproved review rows;
2. builds the images for linux/amd64 and linux/arm64 and pushes them to GHCR by
   digest only (untagged);
3. scans every image with Trivy (HIGH/CRITICAL with a fix fail the release) and
   signs it keylessly with cosign;
4. attaches an SPDX SBOM (a cosign attestation and a release asset) and SLSA
   build provenance;
5. only then tags the verified digest, and checks that each tag resolves to it:
   - `ghcr.io/<owner>/raggie-{edge,control-plane,workers,web,mockllm}:X.Y.Z`;
   - `raggie-embeddings:X.Y.Z-local` (models baked in) and `-slim` (BM25 only).

   An image that fails a gate is never reachable under a release tag. A failed
   run leaves only untagged digests behind.
6. creates the GitHub Release:
   - notes from the changelog section, plus a "Verify" block;
   - `install.sh`, pinned to the version (`RAGGIE_DEFAULT_VERSION`), and `install.sh.sha256`;
   - `raggie-X.Y.Z.tar.gz` (a `git archive` of the tag) and `SHA256SUMS`;
   - the SBOMs and the Linux `THIRD_PARTY_NOTICES.md`.

## 4. Verify the published release

```bash
v=0.1.0 owner=<owner>
cosign verify ghcr.io/$owner/raggie-edge:$v \
  --certificate-identity-regexp "^https://github.com/$owner/raggie/.github/workflows/release.yml@refs/tags/" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
gh attestation verify oci://ghcr.io/$owner/raggie-edge:$v --repo $owner/raggie
gh release download v$v --repo $owner/raggie -p 'SHA256SUMS' -p 'install.sh' -p "raggie-$v.tar.gz"
sha256sum -c SHA256SUMS
```

Repeat `cosign verify` for each image. Then run a fresh install from the
published installer on a scratch machine
(`curl -fsSL …/install.sh | bash -s -- --yes`), sign in, upload a document and
ask a question that cites it.

## 5. After the first release: expected nightly results

- **`notices-fresh`** stays red until the Linux-generated notices are
  committed. A macOS-generated file lists `darwin` packages. Take the
  `third-party-notices-linux` artifact from the nightly run (or the release
  asset), commit it, and the job turns green.
- **DAST (OWASP ZAP)** may be red on its first run: new alerts need either a
  fix or a reviewed entry in `.zap/rules.tsv`. Treat every High as a release
  blocker for the next version.
- **DR drill** (weekly, [`dr-drill.yml`](../.github/workflows/dr-drill.yml)):
  commit the `docs/benchmarks/dr-drill.md` from a green run to publish the
  measured RPO/RTO.

## GitHub settings checklist (once, before the first release)

Everything below except the first item, the two contact addresses and the
Discussions categories is applied by
[`scripts/github/apply-settings.sh`](../scripts/github/apply-settings.sh): run it
without flags to print every call (dry-run, reads only), then with `--apply`. It
is idempotent, so rerun it after changing a workflow's job names. Then
[`scripts/github/open-seed-issues.sh`](../scripts/github/open-seed-issues.sh)
opens the first `good first issue` / `help wanted` issues, skipping titles that
already exist.

- [ ] **Fresh public repository, one squashed commit**: create the public repo's
      first commit from `git archive` of the release commit, after the preflight
      passed on a clean working tree (so every deletion is committed). Never push
      the development repository's history: it still contains files that were
      removed before the release, such as the old `documents/` test corpus. The
      commit is signed off like every other one:

      ```bash
      mkdir raggie-public && git archive HEAD | tar -x -C raggie-public
      cd raggie-public && git init -b main && git add -A
      git commit -s -m "Initial public release"   # adds Signed-off-by: Ali Can Gündüz <your git e-mail>
      git log -1 --format=%B | grep '^Signed-off-by: '
      ```
- [ ] **Branch protection on `main`** (repository ruleset "main"):
  - pull requests required, at least one approving review including a code
    owner, stale approvals dismissed, squash merge only;
  - required status checks: the CI jobs, the docs link check and DCO
    ([`dco.yml`](../.github/workflows/dco.yml), plain git, no app), read from
    the workflow files (`uv run scripts/github/settings.py checks`). A workflow
    with a pull_request `paths` filter (install-smoke.yml) is left out, because
    its check never reports on other PRs and would block them; the installer
    tests also run in CI's `security / sast` job;
  - linear history, no force pushes or deletions; signed commits optional
    (`--require-signed-commits`);
  - admins may merge a PR past the rules (a sole maintainer cannot approve their
    own PR) but never push to `main` directly; `--no-admin-bypass` removes this.
- [ ] **Tag protection** (ruleset "release tags"): only admins (and maintainers,
      in an organization repository) may create, move or delete `v*` tags.
- [ ] **Secret scanning** and **push protection** enabled.
- [ ] **Private vulnerability reporting** enabled (Security → Advisories), and
      the contact address in [SECURITY.md](../SECURITY.md) filled in.
- [ ] The enforcement contact in [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) filled in.
- [ ] **Discussions** enabled (Q&A and Ideas categories).
- [ ] **Dependabot** alerts and security updates enabled.
- [ ] **Actions**: GitHub-owned actions plus the third-party actions the
      workflows use, SHA pinning required; workflow permissions read-only by
      default; "Allow GitHub Actions to create and approve pull requests" off.
- [ ] **Labels** from [`scripts/github/labels.tsv`](../scripts/github/labels.tsv).
- [ ] **GHCR packages** public after the first release (Packages → Package settings →
      visibility); the API cannot do this, and the packages only exist after the first push.
