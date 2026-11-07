# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash
# One PASS and one FAIL case per preflight check (see run.sh / fixture.sh).
# Forbidden strings are assembled at run time so this file never trips the scan.

status_of() { # CHECK → PASS|WARN|FAIL of its (first) row
  printf '%s\n' "$OUT" | awk -v c="$1" '$2 == c { print $1; exit }'
}
expect() { # CHECK STATUS
  preflight "$1"
  [[ "$(status_of "$1")" == "$2" ]] || fail_test "$1: want $2"$'\n'"$OUT"
  if [[ "$2" == FAIL ]]; then ((RC == 1)) || fail_test "$1: exit $RC, want 1"; else ((RC == 0)) || fail_test "$1: exit $RC"$'\n'"$OUT"; fi
}

test_clean_fixture_passes_every_offline_check() {
  preflight changelog,git,i18n,config-docs,spdx,notices,forbidden,images,installer
  ((RC == 0)) || fail_test "clean fixture must pass (exit $RC)"$'\n'"$OUT"
  assert_not_contains "$OUT" "FAIL "
}

test_changelog() {
  expect changelog PASS
  sed -i.bak 's/## \[1.2.3\] - 2026-11-04/## [1.2.4] - 2026-11-04/' "$T/repo/CHANGELOG.md"
  rm "$T/repo/CHANGELOG.md.bak" && commit_all
  expect changelog FAIL
  assert_contains "$OUT" "no section for 1.2.3"
}

test_changelog_date_placeholder() {
  sed -i.bak "s/## \[1.2.3\] - 2026-11-04/## [1.2.3] - TODO(release-$(printf date))/" "$T/repo/CHANGELOG.md"
  rm "$T/repo/CHANGELOG.md.bak" && commit_all
  expect changelog FAIL
  assert_contains "$OUT" "date"
}

test_changelog_empty_section() {
  python3 - "$T/repo/CHANGELOG.md" <<'PY'
import sys
p = sys.argv[1]
t = open(p).read().replace("### Added\n\n- Something useful.\n", "")
open(p, "w").write(t)
PY
  commit_all
  expect changelog FAIL
}

test_git_tree_and_tag() {
  expect git PASS
  printf 'x\n' >"$T/repo/untracked.txt"
  expect git FAIL
  assert_contains "$OUT" "not clean"
  rm "$T/repo/untracked.txt"
  git -C "$T/repo" tag v1.2.3
  expect git PASS
  assert_contains "$OUT" "v1.2.3 points at HEAD"
  printf 'more\n' >>"$T/repo/main.go" && commit_all
  expect git FAIL
  assert_contains "$OUT" "another commit"
}

test_i18n() {
  expect i18n PASS
  printf '{"chat": {"send": "Gönder"}, "title": "B", "extra": "x"}\n' >"$T/repo/web/messages/tr.json"
  commit_all
  expect i18n FAIL
  assert_contains "$OUT" "chat.nested.a"
}

test_i18n_duplicate_keys() {
  printf '{"chat": {"send": "Gönder", "send": "again", "nested": {"a": "A"}}, "title": "B"}\n' \
    >"$T/repo/web/messages/tr.json"
  commit_all
  expect i18n FAIL
  assert_contains "$OUT" "duplicate"
}

test_config_docs() {
  expect config-docs PASS
  printf 'NEW_KNOB=1   # added without regenerating\n' >>"$T/repo/.env.example"
  commit_all
  expect config-docs FAIL
}

test_spdx() {
  expect spdx PASS
  printf 'package main\n' >"$T/repo/other.go" && commit_all
  expect spdx FAIL
}

test_notices() {
  expect notices PASS
  python3 - "$T/repo/THIRD_PARTY_NOTICES.md" <<'PY'
import sys
p = sys.argv[1]
t = open(p).read().replace(
    "None.",
    "| Component | Package | Version | License | Category |\n|---|---|---|---|---|\n"
    "| npm | evil | 1 | GPL-3.0 | copyleft |",
)
open(p, "w").write(t)
PY
  commit_all
  expect notices FAIL
}

test_notices_platform_packages_warn() {
  printf '| @img/sharp-libvips-%s-arm64 | 1.0 | LGPL-3.0 | u |\n' "$(printf darwin)" \
    >>"$T/repo/THIRD_PARTY_NOTICES.md"
  commit_all
  preflight notices
  assert_contains "$OUT" "WARN  notices-platform"
}

test_forbidden_content() {
  expect forbidden PASS
  local ip="45.145.22.$((70 + 4))"
  printf 'server: %s\n' "$ip" >"$T/repo/docs/deploy.md"
  commit_all
  expect forbidden FAIL
  assert_contains "$OUT" "docs/deploy.md"
  assert_contains "$OUT" "live server"
}

test_forbidden_contact_placeholder() {
  printf 'Email TODO(%s)\n' "security-email" >"$T/repo/SECURITY.md"
  commit_all
  expect forbidden FAIL
  assert_contains "$OUT" "SECURITY.md"
}

test_forbidden_paths() {
  mkdir -p "$T/repo/internal"
  printf 'private\n' >"$T/repo/internal/RUNBOOK.md"
  git -C "$T/repo" add -f internal/RUNBOOK.md && commit_all
  expect forbidden FAIL
  assert_contains "$OUT" "internal/RUNBOOK.md"
}

test_forbidden_ignores_gitignored_files_and_itself() {
  printf 'secret.local\n' >"$T/repo/.gitignore"
  printf 'server 45.145.22.%s\n' "$((70 + 4))" >"$T/repo/secret.local"
  commit_all
  expect forbidden PASS
}

test_forbidden_keeps_odd_file_names_intact() {
  local ip="45.145.22.$((70 + 4))"
  printf 'server %s\n' "$ip" >"$T/repo/docs/new"$'\n'"line.md"
  printf 'server %s\n' "$ip" >"$T/repo/docs/-rf with space.md"
  commit_all
  expect forbidden FAIL
  assert_contains "$OUT" 'docs/new\nline.md'
  assert_contains "$OUT" "docs/-rf with space.md"
}

test_forbidden_fails_on_an_unreadable_file() {
  [[ "$(id -u)" != 0 ]] || return 0 # root reads everything
  printf 'harmless\n' >"$T/repo/docs/locked.md"
  commit_all
  chmod 000 "$T/repo/docs/locked.md"
  preflight forbidden
  chmod 644 "$T/repo/docs/locked.md"
  [[ "$(status_of forbidden)" == FAIL ]] || fail_test "an unreadable file must FAIL"$'\n'"$OUT"
  assert_contains "$OUT" "cannot read"
  assert_contains "$OUT" "docs/locked.md"
}

make_pdf() { # FILE TEXT [ENCRYPTED]: a small PDF with a Flate content stream
  python3 - "$@" <<'PY'
import sys, zlib
path, text = sys.argv[1], sys.argv[2]
encrypted = len(sys.argv) > 3
content = b"BT /F1 12 Tf 72 712 Td (" + text.encode() + b") Tj ET"
body = (zlib.compress(content) if not encrypted else b"\x9a\x00garbage-not-zlib\x01")
parts = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n",
         b"1 0 obj << /Length %d /Filter /FlateDecode >>\nstream\n" % len(body), body,
         b"\nendstream\nendobj\n",
         b"2 0 obj << /Length 3 >>\nstream\n\x00\x01\x02\nendstream\nendobj\n"]
if encrypted:
    parts.append(b"trailer << /Encrypt 3 0 R >>\n")
parts.append(b"%%EOF\n")
open(path, "wb").write(b"".join(parts))
PY
}

test_forbidden_scans_text_inside_pdfs() {
  make_pdf "$T/repo/docs/report.pdf" "server 45.145.22.$((70 + 4))"
  commit_all
  RELEASE_PREFLIGHT_PDFTOTEXT=none expect forbidden FAIL
  assert_contains "$OUT" "docs/report.pdf"
}

test_forbidden_scans_text_inside_office_documents() {
  python3 - "$T/repo/docs/plan.docx" "$(printf 'Bulut')" <<'PY'
import sys, zipfile
path, first = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
    # One word split over two runs, as Word does after an edit.
    z.writestr("word/document.xml",
               f"<w:document><w:body><w:p><w:r><w:t>{first}</w:t></w:r>"
               "<w:r><w:t>istan hosting</w:t></w:r></w:p></w:body></w:document>")
PY
  commit_all
  expect forbidden FAIL
  assert_contains "$OUT" "docs/plan.docx"
}

test_forbidden_warns_when_text_cannot_be_extracted() {
  make_pdf "$T/repo/docs/locked.pdf" "anything" encrypted
  commit_all
  RELEASE_PREFLIGHT_PDFTOTEXT=none preflight forbidden
  ((RC == 0)) || fail_test "an unreadable PDF only warns"$'\n'"$OUT"
  assert_contains "$OUT" "WARN  forbidden-extract"
  assert_contains "$OUT" "docs/locked.pdf"
}

test_git_requires_the_tag_on_head_in_ci() {
  RELEASE_PREFLIGHT_REQUIRE_TAG=1 expect git FAIL
  assert_contains "$OUT" "not tagged"
  git -C "$T/repo" tag v1.2.3
  RELEASE_PREFLIGHT_REQUIRE_TAG=1 expect git PASS
}

test_gitleaks() {
  mkdir -p "$T/bin"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$T/bin/gitleaks" && chmod +x "$T/bin/gitleaks"
  RELEASE_PREFLIGHT_GITLEAKS="$T/bin/gitleaks" expect gitleaks PASS
  printf '#!/usr/bin/env bash\necho "leak found" >&2\nexit 1\n' >"$T/bin/gitleaks"
  RELEASE_PREFLIGHT_GITLEAKS="$T/bin/gitleaks" expect gitleaks FAIL
  RELEASE_PREFLIGHT_GITLEAKS=none expect gitleaks WARN
}

test_images() {
  expect images PASS
  printf '  web:\n    image: caddy:latest\n  pgb:\n    image: edoburu/pgbouncer\n' \
    >>"$T/repo/deploy/compose/docker-compose.yml"
  commit_all
  expect images FAIL
  assert_contains "$OUT" "caddy:latest"
  assert_contains "$OUT" "edoburu/pgbouncer"
}

test_images_without_digest_warn() {
  printf '  redis:\n    image: valkey/valkey:8.1-alpine\n' >>"$T/repo/deploy/compose/docker-compose.yml"
  commit_all
  preflight images
  assert_contains "$OUT" "WARN  images-digest"
  ((RC == 0)) || fail_test "a missing digest only warns"
}

test_images_cnpg_image_name() {
  printf 'postgres:\n  cnpg:\n    imageName: ghcr.io/cloudnative-pg/postgresql:17\n' \
    >>"$T/repo/deploy/helm/raggie/values.yaml"
  commit_all
  preflight images
  assert_contains "$OUT" "WARN  images-digest"
  assert_contains "$OUT" "cloudnative-pg/postgresql:17"
}

test_installer() {
  expect installer PASS
  printf '#!/usr/bin/env bash\nVERSION=1\n' >"$T/repo/web/public/install.sh" && commit_all
  expect installer FAIL
}

test_unknown_check_and_bad_version() {
  RC=0
  OUT="$("$PREFLIGHT" 1.2 --repo "$T/repo" 2>&1)" || RC=$?
  ((RC == 2)) || fail_test "a non-semver version is a usage error"
  RC=0
  OUT="$("$PREFLIGHT" 1.2.3 --repo "$T/repo" --only nope 2>&1)" || RC=$?
  ((RC == 2)) || fail_test "an unknown check is a usage error"
}
