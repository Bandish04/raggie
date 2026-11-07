# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash
# Base .env, secrets, upgrade mode and env-file helpers.

full_run() { # the installer's configuration sequence, no Docker
  raggie_env_init "$T"
  raggie_embeddings_configure "$T"
  raggie_llm_configure "$T"
  raggie_env_secrets "$T/.env"
  raggie_env_site "$T/.env"
}

# Deterministic host facts for the site/front-door tests.
raggie_guess_host() { printf '10.1.2.3'; }
r_port_in_use() { [[ " ${BUSY_PORTS:-} " == *" $1 "* ]]; }
r_resolves() { [[ "${RESOLVABLE:-}" == "$1" ]]; }

test_fresh_install_generates_production_secrets() {
  RAGGIE_LOCALE="tr" full_run
  assert_eq "$RAGGIE_SETUP_MODE" fresh
  assert_file_mode "$T/.env" 600
  assert_eq "$(env_of RAGGIE_ENV)" production
  assert_eq "$(env_of NEXT_PUBLIC_DEFAULT_LOCALE)" tr
  local key v
  for key in JWT_SECRET WIDGET_TOKEN_SECRET INTERNAL_API_SECRET SETUP_TOKEN QDRANT_API_KEY; do
    v="$(env_of "$key")"
    assert_match "$v" '^[0-9a-f]{64}$' "$key"
  done
  for key in POSTGRES_PASSWORD REDIS_PASSWORD MINIO_ROOT_PASSWORD; do
    assert_match "$(env_of "$key")" '^[0-9a-f]{48}$' "$key"
  done
  assert_match "$(env_of INTEGRATION_ENC_KEY)" '^[A-Za-z0-9_-]{43}=?$' INTEGRATION_ENC_KEY
  assert_eq "$(env_of DATABASE_URL)" "postgresql://raggie:$(env_of POSTGRES_PASSWORD)@postgres:5432/raggie"
  assert_eq "$(env_of REDIS_URL)" "redis://:$(env_of REDIS_PASSWORD)@redis:6379/0"
  # One public origin (Caddy), plain HTTP without a domain.
  assert_eq "$(env_of PUBLIC_WEB_URL)" http://10.1.2.3
  assert_eq "$(env_of WIDGET_EMBED_BASE_URL)" http://10.1.2.3
  assert_eq "$(env_of RAGGIE_DOMAIN)" ""
  assert_eq "$(env_of COOKIE_SECURE)" false "plain-HTTP login needs non-Secure cookies"
  assert_eq "$(env_of ENABLE_HSTS)" false
  assert_not_contains "$(grep -v '^#' "$T/.env")" change-me "placeholder left behind"
}

test_domain_sets_one_https_origin_for_web_and_widget() {
  local out
  out="$(RAGGIE_DOMAIN=chat.example.com RAGGIE_ACME_EMAIL=ops@example.com RESOLVABLE=chat.example.com full_run 2>&1)"
  assert_eq "$(env_of RAGGIE_DOMAIN)" chat.example.com
  assert_eq "$(env_of ACME_EMAIL)" ops@example.com
  assert_eq "$(env_of PUBLIC_WEB_URL)" https://chat.example.com
  assert_eq "$(env_of WIDGET_EMBED_BASE_URL)" https://chat.example.com
  assert_eq "$(env_of COOKIE_SECURE)" true
  assert_eq "$(env_of ENABLE_HSTS)" true
  assert_contains "$out" "ports 80 and 443"
}

test_domain_that_does_not_resolve_warns() {
  local out
  out="$(RAGGIE_DOMAIN=new.example.com full_run 2>&1)"
  assert_contains "$out" "new.example.com does not resolve"
  assert_eq "$(env_of RAGGIE_DOMAIN)" new.example.com
}

test_non_default_ports_are_part_of_the_origin() {
  RAGGIE_HTTP_PORT=8088 full_run
  assert_eq "$(env_of HTTP_PORT)" 8088
  assert_eq "$(env_of PUBLIC_WEB_URL)" http://10.1.2.3:8088
  rm -f "$T/.env"
  RAGGIE_DOMAIN=chat.example.com RAGGIE_HTTPS_PORT=8443 RESOLVABLE=chat.example.com full_run 2>/dev/null
  assert_eq "$(env_of PUBLIC_WEB_URL)" https://chat.example.com:8443
}

test_busy_front_door_port_needs_another_port_under_yes() {
  export BUSY_PORTS="80"
  expect_fail full_run
  assert_contains "$FAIL_OUT" "port 80 is already in use"
  assert_contains "$FAIL_OUT" --http-port
  rm -f "$T/.env"
  RAGGIE_HTTP_PORT=8088 full_run
  assert_eq "$(env_of HTTP_PORT)" 8088
}

test_upgrade_moves_direct_edge_urls_to_caddy_only_when_approved() {
  cp "$T/.env.example" "$T/.env"
  r_env_set "$T/.env" PUBLIC_WEB_URL http://10.1.2.3:3000
  r_env_set "$T/.env" WIDGET_EMBED_BASE_URL http://10.1.2.3:8080
  R_CHANGES=()
  local out
  out="$(full_run 2>&1)"
  assert_eq "$(env_of WIDGET_EMBED_BASE_URL)" http://10.1.2.3:8080 "changed without approval"
  assert_contains "$out" "no longer public"
  unset RAGGIE_SETUP_MODE
  RAGGIE_RECONFIGURE=1 full_run 2>/dev/null
  assert_eq "$(env_of WIDGET_EMBED_BASE_URL)" http://10.1.2.3
  assert_eq "$(env_of PUBLIC_WEB_URL)" http://10.1.2.3
}

test_rerun_is_upgrade_and_never_clobbers() {
  RAGGIE_PUBLIC_URL=http://h.example full_run
  # The user tunes a few values; a newer release adds a setting.
  r_env_set "$T/.env" RETRIEVE_CONTEXT_K 7
  r_env_set "$T/.env" LLMAAS_CHAT_MODEL my-model
  r_env_set "$T/.env.embeddings" EMBEDDINGS_UPSTREAM_API_KEY keep-me
  sed -i.tmp '/^RERANK_TIMEOUT_MS=/d' "$T/.env" && rm -f "$T/.env.tmp"
  local before keys_before
  before="$(cat "$T/.env")"
  keys_before="$(cat "$T/.env.embeddings")"
  local -a secrets=(JWT_SECRET WIDGET_TOKEN_SECRET INTERNAL_API_SECRET SETUP_TOKEN QDRANT_API_KEY
    POSTGRES_PASSWORD REDIS_PASSWORD MINIO_ROOT_PASSWORD INTEGRATION_ENC_KEY DATABASE_URL REDIS_URL)
  local -a old=()
  local s
  for s in "${secrets[@]}"; do old+=("$(env_of "$s")"); done

  R_CHANGES=()
  unset RAGGIE_PUBLIC_URL RAGGIE_SETUP_MODE RAGGIE_LLM RAGGIE_EMBEDDINGS RAGGIE_RERANKER_PRESET
  # A second run with flags that would change things on a fresh install.
  RAGGIE_LOCALE="" full_run

  assert_eq "$RAGGIE_SETUP_MODE" upgrade
  local i
  for i in "${!secrets[@]}"; do assert_eq "$(env_of "${secrets[$i]}")" "${old[$i]}" "${secrets[$i]} rotated"; done
  assert_eq "$(env_of RETRIEVE_CONTEXT_K)" 7 "user edit lost"
  assert_eq "$(env_of LLMAAS_CHAT_MODEL)" my-model "user edit lost"
  assert_eq "$(env_of RERANK_TIMEOUT_MS)" 5000 "new key not added with its default"
  assert_eq "$(keys_of EMBEDDINGS_UPSTREAM_API_KEY)" keep-me ".env.embeddings clobbered"
  assert_eq "$(env_of PUBLIC_WEB_URL)" http://h.example
  # Backups hold the exact pre-run content.
  local -a backups
  backups=("$T"/.env.bak.*)
  assert_eq "$(cat "${backups[0]}")" "$before" ".env backup differs"
  backups=("$T"/.env.embeddings.bak.*)
  local b="${backups[0]}"
  assert_eq "$(cat "$b")" "$keys_before" ".env.embeddings backup differs"
  assert_file_mode "$b" 600
  # The diff summary lists the one real change.
  assert_eq "${#R_CHANGES[@]}" 1 "unexpected changes: ${R_CHANGES[*]}"
  assert_contains "${R_CHANGES[0]}" "RERANK_TIMEOUT_MS added"
}

test_upgrade_keeps_existing_datastore_passwords_even_if_weak() {
  cp "$T/.env.example" "$T/.env" # an old dev install
  R_CHANGES=()
  local out
  out="$(full_run 2>&1)"
  assert_eq "$(env_of POSTGRES_PASSWORD)" raggie "would break the existing Postgres volume"
  assert_eq "$(env_of RAGGIE_ENV)" development "upgrade must not flip a dev install to production"
  assert_contains "$out" "POSTGRES_PASSWORD is a default/placeholder"
  # Token/session secrets are safe to replace.
  assert_match "$(env_of JWT_SECRET)" '^[0-9a-f]{64}$'
  assert_match "$(env_of INTERNAL_API_SECRET)" '^[0-9a-f]{64}$'
}

test_upgrade_reconfigure_switches_embeddings_with_reembed_warning() {
  full_run
  unset RAGGIE_SETUP_MODE RAGGIE_EMBEDDINGS RAGGIE_RERANKER_PRESET
  export RAGGIE_RECONFIGURE=1 RAGGIE_EMBEDDINGS=cloud RAGGIE_EMBEDDINGS_PRESET=openai \
    RAGGIE_EMBEDDINGS_API_KEY=sk-new RAGGIE_ACCEPT_DATA_TRANSFER=1
  raggie_env_init "$T"
  local out
  out="$(raggie_embeddings_configure "$T" 2>&1)"
  assert_contains "$out" "must be re-embedded"
  assert_eq "$(env_of EMBEDDINGS_PROVIDER)" openai_compatible
  assert_eq "$(keys_of EMBEDDINGS_UPSTREAM_API_KEY)" sk-new
}

test_env_set_keeps_inline_comments_and_round_trips_values() {
  printf 'A=1   # keep me\nB=x\n' >"$T/f"
  r_env_set "$T/f" A 2
  assert_eq "$(sed -n 1p "$T/f")" "A=2   # keep me"
  r_env_set "$T/f" J '{"task":"retrieval.query"}'
  assert_eq "$(r_env_get "$T/f" J)" '{"task":"retrieval.query"}'
  r_env_set "$T/f" S "has space # and hash"
  assert_eq "$(grep '^S=' "$T/f")" "S='has space # and hash'"
  assert_eq "$(r_env_get "$T/f" S)" "has space # and hash"
  r_env_set "$T/f" P "query: "
  assert_eq "$(r_env_get "$T/f" P)" "query: "
  assert_eq "$(r_env_get "$T/f" B)" x
  expect_fail r_env_set "$T/f" Q "it's"
}

test_env_set_quotes_values_starting_with_a_double_quote() {
  : >"$T/f"
  r_env_set "$T/f" D '"starts-with-quote'
  assert_eq "$(r_env_get "$T/f" D)" '"starts-with-quote'
  assert_eq "$(grep '^D=' "$T/f")" "D='\"starts-with-quote'"
  r_env_set "$T/f" E '"both"'
  assert_eq "$(r_env_get "$T/f" E)" '"both"'
}

test_parse_flags_maps_to_env_and_rejects_unknown() {
  r_parse_flags --yes --embeddings cloud --embeddings-api-key=sk-1 --llm-model gpt-x
  assert_eq "$RAGGIE_YES" 1
  assert_eq "$RAGGIE_EMBEDDINGS" cloud
  assert_eq "$RAGGIE_EMBEDDINGS_API_KEY" sk-1
  assert_eq "$RAGGIE_LLM_MODEL" gpt-x
  expect_fail r_parse_flags --embedings cloud
  assert_contains "$FAIL_OUT" "unknown option: --embedings"
  expect_fail r_parse_flags --yes=1
  expect_fail r_parse_flags --llm
}

test_add_missing_appends_with_comment_block() {
  printf '# Section\n# What A does.\nA=1\nB=2\n' >"$T/example"
  printf 'B=9\n' >"$T/f"
  R_CHANGES=()
  r_env_add_missing "$T/f" "$T/example"
  assert_eq "$(r_env_get "$T/f" A)" 1
  assert_eq "$(r_env_get "$T/f" B)" 9
  assert_contains "$(cat "$T/f")" "# What A does."
  assert_eq "${#R_CHANGES[@]}" 1
}
