# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash disable=SC2034
# Embedding mode configuration (deploy/scripts/configure-embeddings.sh).

fresh() { # configure a fresh install up to (and including) embeddings
  raggie_env_init "$T"
  raggie_embeddings_configure "$T"
}

test_local_default_writes_local_profile_and_no_keys() {
  fresh
  assert_eq "$(env_of EMBEDDINGS_PROVIDER)" local
  assert_eq "$(env_of EMBEDDINGS_MODEL)" intfloat/multilingual-e5-large
  assert_eq "$(env_of EMBEDDING_DIM)" 1024
  assert_eq "$(env_of EMBEDDINGS_BAKE)" dense,sparse,rerank
  assert_eq "$(env_of RERANKER_PROVIDER)" local
  assert_eq "$(env_of RERANK_ENABLED)" true
  assert_eq "$(env_of EMBEDDINGS_UPSTREAM_BASE_URL)" ""
  assert_eq "$RAGGIE_EMBEDDINGS_VARIANT" local
  assert_eq "$(keys_of EMBEDDINGS_UPSTREAM_API_KEY)" ""
  assert_file_mode "$T/.env.embeddings" 600
  assert_eq "$(grep -c . "$FAKE_CURL_LOG" || true)" 0 "local mode must not call out"
}

test_local_without_reranker_bakes_no_rerank_model() {
  RAGGIE_EMBEDDINGS=local RAGGIE_RERANKER_PRESET=none fresh
  assert_eq "$(env_of EMBEDDINGS_BAKE)" dense,sparse
  assert_eq "$(env_of RERANKER_PROVIDER)" none
  assert_eq "$(env_of RERANKER_ENABLED)" false
  assert_eq "$(env_of RERANK_ENABLED)" false
}

test_cloud_openai_probes_then_writes_keys_only_to_env_embeddings() {
  export RAGGIE_EMBEDDINGS=cloud RAGGIE_EMBEDDINGS_PRESET=openai RAGGIE_EMBEDDINGS_API_KEY=sk-test-123456789 \
    RAGGIE_ACCEPT_DATA_TRANSFER=1
  fresh
  assert_eq "$(env_of EMBEDDINGS_PROVIDER)" openai_compatible
  assert_eq "$(env_of EMBEDDINGS_UPSTREAM_BASE_URL)" https://api.openai.com/v1
  assert_eq "$(env_of EMBEDDINGS_MODEL)" text-embedding-3-large
  assert_eq "$(env_of EMBEDDING_DIM)" 1024
  assert_eq "$(env_of EMBEDDINGS_REQUEST_EXTRA_JSON)" '{"dimensions":1024}'
  # Cloud dense + local rerank keeps the reranker model in the image.
  assert_eq "$(env_of EMBEDDINGS_BAKE)" sparse,rerank
  assert_eq "$RAGGIE_EMBEDDINGS_VARIANT" local
  assert_eq "$(keys_of EMBEDDINGS_UPSTREAM_API_KEY)" sk-test-123456789
  assert_file_mode "$T/.env.embeddings" 600
  assert_not_contains "$(cat "$T/.env")" sk-test-123456789 "key leaked into the shared .env"
  local log
  log="$(cat "$FAKE_CURL_LOG")"
  assert_eq "$(grep -c '^POST https://api.openai.com/v1/embeddings auth=sk-test-123456789$' "$FAKE_CURL_LOG")" 2 "query + passage probe"
  assert_not_contains "$(grep '^ARGV' "$FAKE_CURL_LOG")" sk-test-123456789 "key passed on the curl command line"
  assert_contains "$log" '"dimensions": 1024'
}

test_cloud_under_yes_requires_typed_consent_flag() {
  export RAGGIE_EMBEDDINGS=cloud RAGGIE_EMBEDDINGS_PRESET=openai RAGGIE_EMBEDDINGS_API_KEY=sk-x
  raggie_env_init "$T"
  local before
  before="$(cat "$T/.env")"
  expect_fail raggie_embeddings_configure "$T"
  assert_contains "$FAIL_OUT" --accept-data-transfer
  assert_eq "$(cat "$T/.env")" "$before" ".env changed although consent was missing"
  assert_eq "$(grep -c . "$FAKE_CURL_LOG" || true)" 0 "called the provider before consent"
}

test_cloud_probe_dimension_mismatch_writes_nothing() {
  export RAGGIE_EMBEDDINGS=cloud RAGGIE_EMBEDDINGS_PRESET=openai RAGGIE_EMBEDDINGS_API_KEY=sk-x \
    RAGGIE_ACCEPT_DATA_TRANSFER=1 FAKE_EMBED_DIM=512
  raggie_env_init "$T"
  expect_fail raggie_embeddings_configure "$T"
  assert_contains "$FAIL_OUT" "dimension 512 returned, 1024 configured"
  assert_eq "$(env_of EMBEDDINGS_PROVIDER)" local
  [[ ! -f "$T/.env.embeddings" ]] || fail_test ".env.embeddings written after a failed probe"
}

test_cloud_probe_detects_broken_query_passage_asymmetry() {
  export RAGGIE_EMBEDDINGS=cloud RAGGIE_EMBEDDINGS_PRESET=mistral RAGGIE_EMBEDDINGS_API_KEY=m-x \
    RAGGIE_ACCEPT_DATA_TRANSFER=1 FAKE_EMBED_MODE=flip
  raggie_env_init "$T"
  expect_fail raggie_embeddings_configure "$T"
  assert_contains "$FAIL_OUT" "query/passage settings"
  assert_eq "$(env_of EMBEDDINGS_PROVIDER)" local
}

test_cloud_probe_http_error_is_reported() {
  export RAGGIE_EMBEDDINGS=cloud RAGGIE_EMBEDDINGS_PRESET=openai RAGGIE_EMBEDDINGS_API_KEY=bad \
    RAGGIE_ACCEPT_DATA_TRANSFER=1 FAKE_EMBED_STATUS=401
  raggie_env_init "$T"
  expect_fail raggie_embeddings_configure "$T"
  assert_contains "$FAIL_OUT" "HTTP 401"
}

test_skip_probe_writes_without_calling_out() {
  export RAGGIE_EMBEDDINGS=cloud RAGGIE_EMBEDDINGS_PRESET=jina RAGGIE_EMBEDDINGS_API_KEY=jina_x \
    RAGGIE_ACCEPT_DATA_TRANSFER=1 RAGGIE_SKIP_PROBE=1
  fresh
  assert_eq "$(env_of EMBEDDINGS_QUERY_EXTRA_JSON)" '{"task":"retrieval.query"}'
  assert_eq "$(env_of EMBEDDINGS_PASSAGE_EXTRA_JSON)" '{"task":"retrieval.passage"}'
  # Jina's default reranker is Jina's (Cohere-compatible) API with the same key.
  assert_eq "$(env_of RERANKER_PROVIDER)" cohere
  assert_eq "$(env_of RERANKER_UPSTREAM_URL)" https://api.jina.ai/v1/rerank
  assert_eq "$(keys_of RERANKER_UPSTREAM_API_KEY)" jina_x
  assert_eq "$(env_of EMBEDDINGS_BAKE)" sparse
  assert_eq "$RAGGIE_EMBEDDINGS_VARIANT" slim
  assert_eq "$(grep -c . "$FAKE_CURL_LOG" || true)" 0
}

test_voyage_probes_rerank_with_voyage_dialect_and_shared_key() {
  export RAGGIE_EMBEDDINGS=cloud RAGGIE_EMBEDDINGS_PRESET=voyage RAGGIE_EMBEDDINGS_API_KEY=pa-voyage \
    RAGGIE_ACCEPT_DATA_TRANSFER=1
  fresh
  assert_eq "$(env_of EMBEDDINGS_MODEL)" voyage-3.5
  assert_eq "$(env_of EMBEDDINGS_QUERY_EXTRA_JSON)" '{"input_type":"query"}'
  assert_eq "$(env_of EMBEDDINGS_PASSAGE_EXTRA_JSON)" '{"input_type":"document"}'
  assert_eq "$(env_of RERANKER_PROVIDER)" voyage
  assert_eq "$(env_of RERANKER_MODEL)" rerank-2.5
  assert_eq "$(keys_of RERANKER_UPSTREAM_API_KEY)" pa-voyage
  assert_contains "$(cat "$FAKE_CURL_LOG")" "POST https://api.voyageai.com/v1/rerank auth=pa-voyage"
  assert_contains "$(cat "$FAKE_CURL_LOG")" '"top_k": 2'
  assert_contains "$(cat "$FAKE_CURL_LOG")" '"input_type": "query"'
}

test_custom_endpoint_with_tei_reranker_and_no_keys() {
  export RAGGIE_EMBEDDINGS=cloud RAGGIE_EMBEDDINGS_PRESET=custom RAGGIE_ACCEPT_DATA_TRANSFER=1 \
    RAGGIE_EMBEDDINGS_BASE_URL=http://tei.internal:8080/v1/ RAGGIE_EMBEDDINGS_MODEL=BAAI/bge-m3 \
    RAGGIE_EMBEDDING_DIM=1024 RAGGIE_EMBEDDINGS_QUERY_PREFIX="query: " \
    RAGGIE_RERANKER_PRESET=tei RAGGIE_RERANKER_URL=http://tei.internal:8081/rerank
  fresh
  assert_eq "$(env_of EMBEDDINGS_UPSTREAM_BASE_URL)" http://tei.internal:8080/v1 "trailing slash kept"
  assert_eq "$(env_of EMBEDDINGS_MODEL)" BAAI/bge-m3
  assert_eq "$(env_of EMBEDDINGS_QUERY_PREFIX)" "query: "
  assert_eq "$(env_of RERANKER_PROVIDER)" tei
  assert_eq "$(env_of RERANKER_UPSTREAM_URL)" http://tei.internal:8081/rerank
  assert_eq "$(keys_of EMBEDDINGS_UPSTREAM_API_KEY)" ""
  assert_eq "$RAGGIE_EMBEDDINGS_VARIANT" slim
  assert_contains "$(cat "$FAKE_CURL_LOG")" "POST http://tei.internal:8080/v1/embeddings auth=none"
  assert_contains "$(cat "$FAKE_CURL_LOG")" '"texts": ['
  assert_contains "$(cat "$FAKE_CURL_LOG")" '"query: How many vacation days'
}

test_custom_requires_model_and_dim_under_yes() {
  export RAGGIE_EMBEDDINGS=cloud RAGGIE_EMBEDDINGS_PRESET=custom RAGGIE_ACCEPT_DATA_TRANSFER=1 \
    RAGGIE_EMBEDDINGS_BASE_URL=http://x/v1
  raggie_env_init "$T"
  expect_fail raggie_embeddings_configure "$T"
  assert_contains "$FAIL_OUT" --embeddings-model
}

test_invalid_extra_json_is_rejected() {
  export RAGGIE_EMBEDDINGS=cloud RAGGIE_EMBEDDINGS_PRESET=openai RAGGIE_EMBEDDINGS_API_KEY=k \
    RAGGIE_ACCEPT_DATA_TRANSFER=1 RAGGIE_EMBEDDINGS_REQUEST_EXTRA_JSON='{"dimensions":'
  raggie_env_init "$T"
  expect_fail raggie_embeddings_configure "$T"
  assert_contains "$FAIL_OUT" "JSON object"
}

test_local_mode_with_cloud_reranker_needs_consent() {
  export RAGGIE_EMBEDDINGS=local RAGGIE_RERANKER_PRESET=cohere RAGGIE_RERANKER_API_KEY=co-x
  raggie_env_init "$T"
  expect_fail raggie_embeddings_configure "$T"
  assert_contains "$FAIL_OUT" "cloud reranker"
  RAGGIE_ACCEPT_DATA_TRANSFER=1 raggie_embeddings_configure "$T"
  assert_eq "$(env_of EMBEDDINGS_PROVIDER)" local
  assert_eq "$(env_of RERANKER_PROVIDER)" cohere
  assert_eq "$(env_of RERANKER_UPSTREAM_URL)" https://api.cohere.com/v2/rerank
  assert_eq "$(keys_of RERANKER_UPSTREAM_API_KEY)" co-x
  assert_eq "$(env_of EMBEDDINGS_BAKE)" dense,sparse
}

test_reranker_probe_failure_aborts_before_writing() {
  export RAGGIE_EMBEDDINGS=cloud RAGGIE_EMBEDDINGS_PRESET=voyage RAGGIE_EMBEDDINGS_API_KEY=pa-voyage \
    RAGGIE_ACCEPT_DATA_TRANSFER=1 FAKE_RERANK_STATUS=500
  raggie_env_init "$T"
  expect_fail raggie_embeddings_configure "$T"
  assert_contains "$FAIL_OUT" "reranker probe"
  assert_eq "$(env_of EMBEDDINGS_PROVIDER)" local
  [[ ! -f "$T/.env.embeddings" ]] || fail_test ".env.embeddings written after a failed rerank probe"
}

test_standalone_reconfigure_to_a_cloud_reranker_generates_the_bearer_secret() {
  # The gateway requires INTERNAL_API_SECRET once an upstream key sits behind it;
  # the installer generates it, a standalone reconfigure must too.
  export RAGGIE_EMBEDDINGS=local RAGGIE_RERANKER_PRESET=cohere RAGGIE_RERANKER_API_KEY=co-x \
    RAGGIE_ACCEPT_DATA_TRANSFER=1
  fresh
  assert_eq "$(env_of INTERNAL_API_SECRET)" ""
  raggie_embeddings_ensure_secret "$T/.env"
  assert_match "$(env_of INTERNAL_API_SECRET)" '^[0-9a-f]{64}$'
  local kept
  kept="$(env_of INTERNAL_API_SECRET)"
  raggie_embeddings_ensure_secret "$T/.env" && fail_test "an existing secret was replaced"
  assert_eq "$(env_of INTERNAL_API_SECRET)" "$kept"
}

test_ensure_secret_leaves_a_fully_local_install_alone() {
  fresh
  raggie_embeddings_ensure_secret "$T/.env" && fail_test "local mode got a secret"
  assert_eq "$(env_of INTERNAL_API_SECRET)" ""
}
