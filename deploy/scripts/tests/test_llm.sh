# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash
# Chat LLM configuration (deploy/scripts/configure-llm.sh).

test_default_is_zero_key_mock() {
  raggie_env_init "$T"
  raggie_llm_configure "$T"
  assert_eq "$RAGGIE_LLM" mock
  assert_eq "$(env_of LLMAAS_BASE_URL)" http://mockllm:11435/v1
  assert_eq "$(env_of LLMAAS_API_KEY)" mock
  assert_eq "$(grep -c . "$FAKE_CURL_LOG" || true)" 0
}

test_openai_compatible_probes_models_with_bearer() {
  export RAGGIE_LLM=openai RAGGIE_LLM_BASE_URL=https://llm.example.com/v1/ RAGGIE_LLM_API_KEY=sk-llm-abcdef123 \
    RAGGIE_LLM_MODEL=gpt-test
  raggie_env_init "$T"
  raggie_llm_configure "$T"
  assert_eq "$(env_of LLMAAS_BASE_URL)" https://llm.example.com/v1
  assert_eq "$(env_of LLMAAS_API_KEY)" sk-llm-abcdef123
  assert_eq "$(env_of LLMAAS_CHAT_MODEL)" gpt-test
  assert_contains "$(cat "$FAKE_CURL_LOG")" "GET https://llm.example.com/v1/models auth=sk-llm-abcdef123"
  assert_not_contains "$(grep '^ARGV' "$FAKE_CURL_LOG")" sk-llm-abcdef123 "key on the curl command line"
}

test_model_defaults_to_first_listed_model() {
  export RAGGIE_LLM=self-hosted RAGGIE_LLM_BASE_URL=http://10.0.0.5:11434/v1
  raggie_env_init "$T"
  raggie_llm_configure "$T"
  assert_eq "$(env_of LLMAAS_CHAT_MODEL)" gpt-test
  assert_eq "$(env_of LLMAAS_API_KEY)" none "a keyless server gets a non-empty placeholder"
  assert_contains "$(cat "$FAKE_CURL_LOG")" "auth=none"
}

test_unlisted_model_warns_but_is_kept() {
  export RAGGIE_LLM=openai RAGGIE_LLM_BASE_URL=https://llm.example.com/v1 RAGGIE_LLM_API_KEY=k \
    RAGGIE_LLM_MODEL=my-finetune
  raggie_env_init "$T"
  local out
  out="$(raggie_llm_configure "$T" 2>&1)"
  assert_contains "$out" "not in the endpoint's /models list"
}

test_probe_failure_aborts_without_writing() {
  export RAGGIE_LLM=openai RAGGIE_LLM_BASE_URL=https://llm.example.com/v1 RAGGIE_LLM_API_KEY=wrong \
    RAGGIE_LLM_MODEL=gpt-test FAKE_MODELS_STATUS=401
  raggie_env_init "$T"
  local before
  before="$(env_of LLMAAS_BASE_URL)"
  expect_fail raggie_llm_configure "$T"
  assert_contains "$FAIL_OUT" "HTTP 401"
  assert_eq "$(env_of LLMAAS_BASE_URL)" "$before"
}

test_openai_requires_key_under_yes() {
  export RAGGIE_LLM=openai RAGGIE_LLM_BASE_URL=https://llm.example.com/v1
  raggie_env_init "$T"
  expect_fail raggie_llm_configure "$T"
  assert_contains "$FAIL_OUT" --llm-api-key
}

test_bundled_ollama_uses_the_overlay_model_without_calling_out() {
  export RAGGIE_LLM=ollama RAGGIE_OLLAMA_MODEL=qwen3:8b RAGGIE_GPU=no
  raggie_env_init "$T"
  raggie_llm_configure "$T"
  assert_eq "$(env_of OLLAMA_MODEL)" qwen3:8b
  assert_eq "$(env_of LLMAAS_BASE_URL)" http://ollama:11434/v1
  assert_eq "$(env_of LLMAAS_CHAT_MODEL)" qwen3:8b
  assert_eq "$RAGGIE_GPU" 0
  assert_eq "$(grep -c . "$FAKE_CURL_LOG" || true)" 0
}

test_gpu_auto_detects_nvidia_smi() {
  mkdir -p "$T/bin"
  printf '#!/bin/sh\nexit 0\n' >"$T/bin/nvidia-smi"
  chmod +x "$T/bin/nvidia-smi"
  export PATH="$T/bin:$PATH" RAGGIE_LLM=ollama
  raggie_env_init "$T"
  raggie_llm_configure "$T"
  assert_eq "$RAGGIE_GPU" 1
  assert_eq "$(env_of OLLAMA_MODEL)" qwen3:4b-instruct "default model from .env.example"
}

test_upgrade_detects_the_installed_llm_mode() {
  export RAGGIE_LLM=ollama RAGGIE_GPU=no
  raggie_env_init "$T"
  raggie_llm_configure "$T"
  unset RAGGIE_LLM RAGGIE_GPU RAGGIE_SETUP_MODE
  raggie_env_init "$T"
  raggie_llm_configure "$T"
  assert_eq "$RAGGIE_LLM" ollama
}

test_http_bearer_never_touches_the_disk() {
  mkdir -p "$T/tmp"
  # Any temp file lands where the fake curl looks (macOS mktemp ignores TMPDIR).
  mktemp() { command mktemp "$T/tmp/tmp.XXXXXX"; }
  FAKE_CURL_SCAN_DIR="$T/tmp" r_http GET "https://llm.example.com/v1/models" "sk-secret-token"
  assert_eq "$R_HTTP_STATUS" 200
  assert_contains "$(cat "$FAKE_CURL_LOG")" "auth=sk-secret-token"
  assert_not_contains "$(cat "$FAKE_CURL_LOG")" "LEAK" "a header file with the bearer was written"
  assert_eq "$(find "$T/tmp" -type f | wc -l | tr -d ' ')" 0
}
