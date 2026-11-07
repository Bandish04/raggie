#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Unit tests for the 0.1.0 upgrade helpers (pure logic only, no Docker).
#   bash scripts/upgrade/0.1.0/tests/test_lib.sh
# shellcheck source-path=SCRIPTDIR/..
set -uo pipefail

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC2034 # read by the sourced scripts: load functions only
UPGRADE_LIB_ONLY=1
# shellcheck source=preflight.sh
. "$SCRIPTS/preflight.sh"
# shellcheck source=drain-queues.sh
. "$SCRIPTS/drain-queues.sh"
# shellcheck source=migrate-objectstore.sh
. "$SCRIPTS/migrate-objectstore.sh"

failures=0
tests=0
truth() { if "$@"; then echo yes; else echo no; fi; }
eq() { # eq <name> <expected> <actual>
  tests=$((tests + 1))
  if [[ "$2" != "$3" ]]; then
    failures=$((failures + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3"
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ── env_get ────────────────────────────────────────────────────────────────
cat >"$TMP/env" <<'EOF'
# comment
PLAIN=abc
INLINE=value   # trailing comment
HASHED=pa#ss
SQ='with # hash'
DQ="double quoted"
export EXPORTED=yes
EMPTY=
DUP=first
DUP=second
SPACED = nope
EOF
eq env-plain "abc" "$(env_get "$TMP/env" PLAIN)"
eq env-inline-comment "value" "$(env_get "$TMP/env" INLINE)"
eq env-hash-inside-value "pa#ss" "$(env_get "$TMP/env" HASHED)"
eq env-single-quotes "with # hash" "$(env_get "$TMP/env" SQ)"
eq env-double-quotes "double quoted" "$(env_get "$TMP/env" DQ)"
eq env-export "yes" "$(env_get "$TMP/env" EXPORTED)"
eq env-empty "" "$(env_get "$TMP/env" EMPTY)"
eq env-last-wins "second" "$(env_get "$TMP/env" DUP)"
eq env-missing "" "$(env_get "$TMP/env" NOPE)"
eq env-has-empty yes "$(truth env_has "$TMP/env" EMPTY)"
eq env-has-missing no "$(truth env_has "$TMP/env" NOPE)"

# ── secret_problem (mirrors the services' boot checks) ──────────────────────
eq secret-ok "" "$(secret_problem "$(printf 'x%.0s' {1..40})" 32)"
eq secret-short "is shorter than 32 bytes" "$(secret_problem short 32)"
eq secret-default "is a known default" "$(secret_problem raggie-minio 16)"
eq secret-default-case "is a known default" "$(secret_problem MinioAdmin 16)"
eq secret-placeholder "is a placeholder" \
  "$(secret_problem dev-insecure-jwt-secret-change-me-please-xxxxxxxx 32)"
eq secret-changeme "is a placeholder" "$(secret_problem "CHANGEME-$(printf 'y%.0s' {1..40})" 32)"
eq secret-empty "is empty" "$(secret_problem "" 32)"
# Byte length, not character length (the services count bytes).
eq secret-bytes "" "$(secret_problem "ğğğğğğğğ" 16)"

# ── URLs ───────────────────────────────────────────────────────────────────
eq url-pass "s3cr%t" "$(url_password 'redis://:s3cr%25t@redis:6379/0')"
eq url-user-pass "pw" "$(url_password 'postgresql://raggie:pw@db:5432/raggie')"
eq url-no-pass "" "$(url_password 'redis://redis:6379')"
eq url-user-only "" "$(url_password 'redis://default@redis:6379')"
# printf %b must not interpret backslashes: only %XX is decoded.
eq url-backslash 'a\nb\\c' "$(url_password 'redis://:a\nb\\c@redis:6379')"
eq url-pct-backslash 'a\b' "$(url_password 'redis://:a%5Cb@redis:6379')"
eq url-pct-at-percent 'p@ss%w' "$(url_password 'redis://:p%40ss%25w@redis:6379')"
eq url-bad-pct '%zz' "$(url_password 'redis://:%zz@redis:6379')"

# ── semver ─────────────────────────────────────────────────────────────────
eq semver-gt yes "$(truth semver_gt 1.19.0 1.18.3)"
eq semver-eq no "$(truth semver_gt 1.18.3 1.18.3)"
eq semver-numeric no "$(truth semver_gt 1.9.9 1.18.3)"
eq semver-v-prefix yes "$(truth semver_gt v1.18.10 1.18.3)"

# ── Qdrant upgrade path (no downgrade, no skipped minor on a single node) ──
eq qdrant-target "1.20.0" "$QDRANT_TARGET_VERSION"
eq qdrant-same "PASS" "$(qdrant_verdict 1.20.0 | cut -d'|' -f1)"
eq qdrant-one-minor-behind "PASS" "$(qdrant_verdict 1.19.0 | cut -d'|' -f1)"
eq qdrant-newer "FAIL|cannot downgrade" "$(qdrant_verdict 1.21.0 | cut -d'|' -f1)|$(qdrant_verdict 1.21.0 | grep -o 'cannot downgrade')"
eq qdrant-newer-patch "FAIL" "$(qdrant_verdict v1.20.1 | cut -d'|' -f1)"
eq qdrant-two-minors-hop "FAIL|qdrant/qdrant:v1.19.2" \
  "$(qdrant_verdict 1.18.3 | cut -d'|' -f1)|$(qdrant_verdict 1.18.3 | grep -o 'qdrant/qdrant:v1.19.2')"
eq qdrant-three-minors-hop "FAIL|qdrant/qdrant:v1.18.3" \
  "$(qdrant_verdict 1.17.1 | cut -d'|' -f1)|$(qdrant_verdict 1.17.1 | grep -o 'qdrant/qdrant:v1.18.3')"
eq qdrant-ancient "FAIL|every minor" \
  "$(qdrant_verdict 1.12.0 | cut -d'|' -f1)|$(qdrant_verdict 1.12.0 | grep -o 'every minor')"
eq qdrant-major "FAIL" "$(qdrant_verdict 0.11.0 | cut -d'|' -f1)"

# ── XINFO parsing ──────────────────────────────────────────────────────────
XINFO_GROUPS=$'name\nother\nconsumers\n0\npending\n9\nlast-delivered-id\n5-0\nentries-read\n5\nlag\n4\nname\ningestion-workers\nconsumers\n2\npending\n3\nlast-delivered-id\n1700000000000-7\nentries-read\n120\nlag\n0'
eq xinfo-group "3 0 1700000000000-7" \
  "$(printf '%s\n' "$XINFO_GROUPS" | parse_xinfo_groups ingestion-workers)"
eq xinfo-other-group "9 4 5-0" "$(printf '%s\n' "$XINFO_GROUPS" | parse_xinfo_groups other)"
eq xinfo-missing-group "" "$(printf '%s\n' "$XINFO_GROUPS" | parse_xinfo_groups nope)"
# lag is nil (empty line) when Redis can't compute it.
eq xinfo-nil-lag "0 nil 9-0" \
  "$(printf 'name\ng\nconsumers\n1\npending\n0\nlast-delivered-id\n9-0\nentries-read\n\nlag\n\n' \
    | parse_xinfo_groups g)"
eq xinfo-stream-last-id "12-3" \
  "$(printf 'length\n4\nradix-tree-keys\n1\nlast-generated-id\n12-3\nmax-deleted-entry-id\n0-0\n' \
    | parse_xinfo_stream_field last-generated-id)"

# ── backlog decision ───────────────────────────────────────────────────────
eq backlog-drained 0 "$(group_backlog '0 0 5-0' '5-0')"
eq backlog-pending 3 "$(group_backlog '3 0 5-0' '5-0')"
eq backlog-lag 7 "$(group_backlog '0 7 5-0' '9-0')"
# nil lag: fall back to comparing the last delivered and last generated ids.
eq backlog-nil-lag-drained 0 "$(group_backlog '0 nil 9-0' '9-0')"
eq backlog-nil-lag-behind unknown "$(group_backlog '0 nil 5-0' '9-0')"
eq backlog-no-group 0 "$(group_backlog '' '')"

# ── preflight env checks (table rows) ─────────────────────────────────────
STRONG="$(printf 's%.0s' {1..48})"
PW="Str0ng-Postgres-Passw0rd"
write_env() { printf '%s\n' "$@" >"$TMP/p.env"; }
rows() { RESULTS=(); "$@" "$TMP/p.env"; printf '%s\n' "${RESULTS[@]}"; }

write_env "RAGGIE_ENV=production" "JWT_SECRET=$STRONG" "WIDGET_TOKEN_SECRET=$STRONG" \
  "POSTGRES_PASSWORD=$PW" "DATABASE_URL=postgresql://raggie:$PW@postgres:5432/raggie" \
  "MINIO_ROOT_PASSWORD=m1n10-Str0ng-Passw0rd" "INTERNAL_API_SECRET="
out="$(rows check_secrets)"
eq preflight-secrets-pass "" "$(grep -v '^PASS' <<<"$out")"

write_env "RAGGIE_ENV=" "JWT_SECRET=dev-insecure-jwt-secret-change-me-please" \
  "WIDGET_TOKEN_SECRET=$STRONG" "POSTGRES_PASSWORD=raggie" "MINIO_ROOT_PASSWORD=raggie-minio" \
  "INTERNAL_API_SECRET=short" "QDRANT_API_KEY=abc"
out="$(rows check_secrets)"
eq preflight-secrets-jwt "FAIL|secret JWT_SECRET|is a known default" "$(grep 'JWT_SECRET' <<<"$out")"
eq preflight-secrets-optional-short "FAIL|secret INTERNAL_API_SECRET|is shorter than 32 bytes" \
  "$(grep 'INTERNAL_API_SECRET' <<<"$out")"
eq preflight-secrets-pg "FAIL|secret POSTGRES_PASSWORD|is a known default" \
  "$(grep 'POSTGRES_PASSWORD' <<<"$out")"
eq preflight-secrets-db-url-missing "FAIL|DATABASE_URL|missing (the edge refuses to start without it)" \
  "$(grep '|DATABASE_URL|' <<<"$out")"
QDRANT_FIX="rotate QDRANT_API_KEY (and restart Qdrant with the new key)"
eq preflight-secrets-qdrant "FAIL|secret QDRANT_API_KEY|is shorter than 32 bytes; $QDRANT_FIX" \
  "$(grep 'QDRANT_API_KEY' <<<"$out")"
# QDRANT_API_KEY: empty is allowed; when set, >= 32 bytes and no default/placeholder
# (the cp, workers and edge boot rule).
qdrant_row() { write_env "RAGGIE_ENV=production" "QDRANT_API_KEY=$1"; rows check_secrets | grep 'QDRANT_API_KEY'; }
eq preflight-qdrant-empty "PASS|secret QDRANT_API_KEY|not set (optional)" "$(qdrant_row "")"
eq preflight-qdrant-strong "PASS|secret QDRANT_API_KEY|ok (48 bytes)" "$(qdrant_row "$STRONG")"
eq preflight-qdrant-31 "FAIL|secret QDRANT_API_KEY|is shorter than 32 bytes; $QDRANT_FIX" \
  "$(qdrant_row "$(printf 'q%.0s' {1..31})")"
eq preflight-qdrant-placeholder "FAIL|secret QDRANT_API_KEY|is a placeholder; $QDRANT_FIX" \
  "$(qdrant_row "change-me-$(printf 'q%.0s' {1..40})")"
eq preflight-env-empty-means-prod "WARN|RAGGIE_ENV|empty = production: every secret check below applies" \
  "$(grep '|RAGGIE_ENV|' <<<"$out")"
# Values never leak into the report.
eq preflight-no-values "" "$(grep -E 'dev-insecure|raggie-minio|short' <<<"$out" | grep -v 'is short' || true)"

write_env "RAGGIE_ENV=development" "JWT_SECRET=x"
eq preflight-dev-skips "WARN|secrets|RAGGIE_ENV=development: the services skip secret checks; set production on a server" \
  "$(rows check_secrets)"

write_env "REDIS_PASSWORD=$STRONG" "REDIS_URL=redis://redis:6379"
eq preflight-redis-missing-in-url \
  "FAIL|REDIS_URL / REDIS_PASSWORD|REDIS_PASSWORD is set but REDIS_URL carries no password (use redis://:<password>@redis:6379/0)" \
  "$(rows check_redis)"
write_env "REDIS_PASSWORD=$STRONG" "REDIS_URL=redis://:other@redis:6379/0"
eq preflight-redis-differs "FAIL|REDIS_URL / REDIS_PASSWORD|REDIS_URL carries a different password than REDIS_PASSWORD" \
  "$(rows check_redis)"
write_env "REDIS_PASSWORD=$STRONG" "REDIS_URL=redis://:$STRONG@redis:6379/0"
eq preflight-redis-ok "PASS|REDIS_URL / REDIS_PASSWORD|consistent (auth on)" "$(rows check_redis)"
write_env "REDIS_PASSWORD=" "REDIS_URL=redis://:pw@redis:6379"
eq preflight-redis-url-only \
  "FAIL|REDIS_URL / REDIS_PASSWORD|REDIS_URL has a password but REDIS_PASSWORD is empty: Valkey would start without auth" \
  "$(rows check_redis)"
write_env "REDIS_URL=redis://redis:6379"
eq preflight-redis-no-auth "WARN|REDIS_URL / REDIS_PASSWORD|no auth: set REDIS_PASSWORD and the same password in REDIS_URL" \
  "$(rows check_redis)"

write_env "WIDGET_EMBED_BASE_URL=http://203.0.113.10:8080"
eq preflight-widget-8080 \
  "FAIL|WIDGET_EMBED_BASE_URL|points at the edge port :8080; 0.1.0 serves the widget from the Caddy origin (http://<host> or https://<RAGGIE_DOMAIN>)" \
  "$(rows check_public_urls | grep WIDGET)"
write_env "RAGGIE_DOMAIN=chat.example.com" "WIDGET_EMBED_BASE_URL=http://chat.example.com"
eq preflight-widget-domain "WARN|WIDGET_EMBED_BASE_URL|differs from https://chat.example.com (the Caddy origin for RAGGIE_DOMAIN)" \
  "$(rows check_public_urls | grep WIDGET)"
write_env "RAGGIE_DOMAIN=" "COOKIE_SECURE=true" "WIDGET_EMBED_BASE_URL=http://10.0.0.5"
eq preflight-cookie-secure-http "WARN|COOKIE_SECURE|true without RAGGIE_DOMAIN: logins fail over plain HTTP" \
  "$(rows check_public_urls | grep COOKIE)"
eq preflight-locale-unset "WARN|NEXT_PUBLIC_DEFAULT_LOCALE|unset: the UI default becomes en (set tr to keep Turkish)" \
  "$(rows check_public_urls | grep LOCALE)"

# Faz 0 bound ports via WEB_PORT=127.0.0.1:3000; 0.1.0 adds 127.0.0.1 itself.
write_env "WEB_PORT=127.0.0.1:3000" "CONTROL_PLANE_PORT=8000" "HTTP_PORT=80"
out="$(rows check_port_vars)"
eq preflight-port-var-host "FAIL|WEB_PORT|must be a plain port number (0.1.0 already binds web, edge and control-plane to 127.0.0.1)" \
  "$(grep '|WEB_PORT|' <<<"$out")"
eq preflight-port-var-ok "PASS|CONTROL_PLANE_PORT|8000" "$(grep '|CONTROL_PLANE_PORT|' <<<"$out")"
eq preflight-port-var-unset "" "$(grep '|EDGE_HOST_PORT|' <<<"$out")"

# ── disk sizing ────────────────────────────────────────────────────────────
eq disk-pass "PASS" "$(disk_verdict $((10 * 1024 * 1024)) $((2 * 1024 * 1024)))"
eq disk-warn "WARN" "$(disk_verdict $((5 * 1024 * 1024)) $((2 * 1024 * 1024)))"
eq disk-fail "FAIL" "$(disk_verdict $((3 * 1024 * 1024)) $((2 * 1024 * 1024)))"

# ── rclone size --json ────────────────────────────────────────────────────
eq rclone-size "1234 987654321" \
  "$(printf '{"count":1234,"bytes":987654321,"sizeless":0}' | parse_rclone_size)"
eq rclone-size-empty "0 0" "$(printf '' | parse_rclone_size)"

printf '%d tests, %d failed\n' "$tests" "$failures"
[[ $failures -eq 0 ]]
