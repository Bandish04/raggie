# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash
# make_fixture DIR: a minimal, release-clean git repo holding the tools the
# preflight runs (copied from this checkout) and one file per checked area.

make_fixture() {
  local d=$1 f
  mkdir -p "$d"
  for f in scripts/gen-config-docs.py scripts/license/spdx.py scripts/notices/check_review.py \
    scripts/release/forbidden.txt .github/workflows/release.yml; do
    mkdir -p "$d/$(dirname "$f")"
    cp "$REPO_ROOT/$f" "$d/$f"
  done
  cat >"$d/CHANGELOG.md" <<'EOF'
# Changelog

## [Unreleased]

## [1.2.3] - 2026-11-04

### Added

- Something useful.

## [1.2.2] - 2026-10-01

- Older.
EOF
  mkdir -p "$d/web/messages" "$d/web/public" "$d/deploy/compose" "$d/deploy/helm/raggie" "$d/docs"
  printf '{"chat": {"send": "Send", "nested": {"a": "A"}}, "title": "T"}\n' >"$d/web/messages/en.json"
  printf '{"chat": {"send": "Gönder", "nested": {"a": "A"}}, "title": "B"}\n' >"$d/web/messages/tr.json"
  printf '#!/usr/bin/env bash\n# SPDX-License-Identifier: Apache-2.0\nRAGGIE_DEFAULT_VERSION="1.2.3"\n' \
    >"$d/web/public/install.sh"
  cat >"$d/deploy/compose/docker-compose.yml" <<'EOF'
services:
  postgres:
    image: postgres:17.11-alpine@sha256:266d3c257594e195b309ae9d1805e54c788f1d7b375f56bf6c367aac6c917e7b
  edge:
    build: { context: ../../services/edge }
    image: raggie/edge:dev
EOF
  cat >"$d/deploy/helm/raggie/values.yaml" <<'EOF'
image:
  tag: ""
web:
  image: { repository: "", tag: "" }
qdrant:
  image: docker.io/qdrant/qdrant:v1.18.3@sha256:0bd98fa7977f1e75694779359ca4e212822e5a71334e28421182f72f209d5286
EOF
  printf '# SPDX-License-Identifier: Apache-2.0\n# Example\nAPP_PORT=8080   # the port\n' >"$d/.env.example"
  printf '# Third-party notices\n\n## Review required\n\nNone.\n\n## Go\n\n| Package | Version | License | URL |\n|---|---|---|---|\n| x | 1 | MIT | u |\n' \
    >"$d/THIRD_PARTY_NOTICES.md"
  : >"$d/scripts/notices/review-allowlist.txt"
  printf '// SPDX-License-Identifier: Apache-2.0\n\npackage main\n' >"$d/main.go"
  (cd "$d" && python3 scripts/gen-config-docs.py >/dev/null)
  git -C "$d" init -q -b main
  git -C "$d" -c user.email=t@example.com -c user.name=t add -A
  git -C "$d" -c user.email=t@example.com -c user.name=t commit -qm init
}

commit_all() {
  git -C "$T/repo" -c user.email=t@example.com -c user.name=t add -A
  git -C "$T/repo" -c user.email=t@example.com -c user.name=t commit -qm change
}

# preflight CHECK → the table in $OUT, the exit code in $RC (read by the tests)
# shellcheck disable=SC2034
preflight() {
  RC=0
  OUT="$("$PREFLIGHT" 1.2.3 --repo "$T/repo" --only "$1" 2>&1)" || RC=$?
}
