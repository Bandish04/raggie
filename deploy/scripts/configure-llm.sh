#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Chat LLM for a Raggie install. Shared by web/public/install.sh and
# `make setup`; runnable alone:
#
#   deploy/scripts/configure-llm.sh [--llm mock|ollama|self-hosted|openai]
#       [--ollama-model ID] [--gpu auto|yes|no]
#       [--llm-base-url URL] [--llm-api-key KEY] [--llm-model ID]
#       [--skip-probe] [--yes]
#
#   mock         deterministic offline demo LLM (no key, no GPU):
#                docker-compose.demo.yml + the `mock` profile
#   ollama       bundled Ollama (docker-compose.ollama.yml, + docker-compose.gpu.yml
#                with an NVIDIA GPU); no key, nothing leaves the host
#   self-hosted  an OpenAI-compatible server you run elsewhere (vLLM, Ollama, TGI);
#                key optional
#   openai       any OpenAI-compatible endpoint with an API key
# Remote endpoints are probed (GET {base}/models) before anything is written.

RAGGIE_MOCK_LLM_URL="http://mockllm:11435/v1"

# raggie_llm_probe BASE KEY — sets L_MODELS (newline-separated ids).
raggie_llm_probe() {
  local base="$1" key="$2"
  r_http GET "$base/models" "$key"
  if [[ "$R_HTTP_STATUS" != 200 ]]; then
    r_warn "LLM probe: GET $base/models -> HTTP $R_HTTP_STATUS ${R_HTTP_BODY:0:200}"
    return 1
  fi
  if r_have_python; then
    L_MODELS="$(python3 -c 'import json,sys; print("\n".join(m["id"] for m in json.loads(sys.argv[1])["data"]))' "$R_HTTP_BODY" 2>/dev/null)" || {
      r_warn "LLM probe: $base/models did not return an OpenAI-style model list"
      return 1
    }
  else
    L_MODELS="$(printf '%s' "$R_HTTP_BODY" | grep -o '"id" *: *"[^"]*"' | sed 's/.*"\([^"]*\)"$/\1/')"
  fi
  r_log "LLM probe ok: $(printf '%s\n' "$L_MODELS" | grep -c .) model(s) at $base"
}

RAGGIE_OLLAMA_URL="http://ollama:11434/v1"

# raggie_llm_installed ROOT — mode of an existing install (state file, else .env).
raggie_llm_installed() {
  local root="$1" mode base
  mode="$(r_env_get "$root/.raggie/state.env" RAGGIE_LLM_MODE)"
  if [[ -n "$mode" && "$mode" != keep ]]; then printf '%s' "$mode"; return 0; fi
  base="$(r_env_get "$root/.env" LLMAAS_BASE_URL)"
  case "$base" in
    "$RAGGIE_MOCK_LLM_URL") printf mock ;;
    "$RAGGIE_OLLAMA_URL") printf ollama ;;
    *) printf keep ;;
  esac
}

# raggie_gpu ROOT — RAGGIE_GPU=1|0 from --gpu auto|yes|no (auto: nvidia-smi works).
raggie_gpu() {
  local want="${RAGGIE_GPU:-}"
  if [[ -z "$want" ]]; then
    want="$(r_env_get "$1/.raggie/state.env" RAGGIE_GPU)"
    [[ -n "$want" ]] || want=auto
  fi
  case "$want" in
    1 | yes | true) RAGGIE_GPU=1 ;;
    0 | no | false) RAGGIE_GPU=0 ;;
    auto)
      if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
        RAGGIE_GPU=1
        r_log "NVIDIA GPU detected: Ollama runs on the GPU (--gpu no to disable)"
      else
        RAGGIE_GPU=0
      fi
      ;;
    *) r_die "--gpu must be auto, yes or no" ;;
  esac
  export RAGGIE_GPU
}

# raggie_llm_configure ROOT — writes the LLM settings to .env; exports RAGGIE_LLM
# (mock|ollama|self-hosted|openai|keep) and RAGGIE_GPU.
raggie_llm_configure() {
  local root="$1" env="$1/.env" gpu_flag="${RAGGIE_GPU:-}"
  if [[ "${RAGGIE_SETUP_MODE:-}" == upgrade && "${RAGGIE_RECONFIGURE:-0}" != 1 && -z "${RAGGIE_LLM:-}" ]]; then
    RAGGIE_LLM="$(raggie_llm_installed "$root")"
    r_log "LLM: keeping $(r_env_get "$env" LLMAAS_BASE_URL) (--reconfigure to change)"
    export RAGGIE_LLM
    if [[ "$RAGGIE_LLM" == ollama ]]; then raggie_gpu "$root"; else RAGGIE_GPU=0; export RAGGIE_GPU; fi
    return 0
  fi

  # Interactive default: the bundled Ollama when the host has room for it.
  local default=mock
  if r_can_prompt && (($(r_mem_mb) >= 12288)); then default=ollama; fi
  r_choose RAGGIE_LLM "Chat LLM:" "$default" \
    "mock|Offline demo LLM — no key, no GPU; templated answers that cite your documents" \
    "ollama|Bundled Ollama ($(r_env_get "$env" OLLAMA_MODEL), ~2.5 GB download, ~4 GB RAM on CPU; nothing leaves the host)" \
    "self-hosted|An OpenAI-compatible server you run (vLLM / Ollama / TGI elsewhere; key optional)" \
    "openai|OpenAI-compatible endpoint with an API key (OpenAI, Azure, Mistral, OpenRouter, ...)"
  RAGGIE_GPU=0
  export RAGGIE_LLM RAGGIE_GPU

  local base="${RAGGIE_LLM_BASE_URL:-}" key="${RAGGIE_LLM_API_KEY:-}" model="${RAGGIE_LLM_MODEL:-}"
  case "$RAGGIE_LLM" in
    mock)
      r_env_set "$env" LLMAAS_BASE_URL "$RAGGIE_MOCK_LLM_URL"
      r_env_set "$env" LLMAAS_API_KEY mock
      [[ -z "$model" ]] || r_env_set "$env" LLMAAS_CHAT_MODEL "$model"
      r_note "    The mock LLM answers deterministically; switch later with deploy/scripts/configure-llm.sh."
      return 0
      ;;
    ollama)
      model="${RAGGIE_OLLAMA_MODEL:-$model}"
      r_ask model "Ollama model" "$(r_env_get "$env" OLLAMA_MODEL)" --ollama-model
      r_env_set "$env" OLLAMA_MODEL "$model"
      # The overlay sets these for the services too; keep .env consistent.
      r_env_set "$env" LLMAAS_BASE_URL "$RAGGIE_OLLAMA_URL"
      r_env_set "$env" LLMAAS_API_KEY ollama
      r_env_set "$env" LLMAAS_CHAT_MODEL "$model"
      RAGGIE_GPU="$gpu_flag"
      raggie_gpu "$root"
      r_note "    First start pulls $model (~2.5 GB for the default); chat waits until it is ready."
      return 0
      ;;
    self-hosted)
      r_note "    Containers reach a server on this host via its LAN address, not localhost."
      r_ask base "OpenAI-compatible base URL (…/v1)" "http://$(raggie_llm_host):11434/v1" --llm-base-url
      r_ask_secret key "API key (empty if none)" --llm-api-key optional
      ;;
    openai)
      r_ask base "OpenAI-compatible base URL (…/v1)" "https://api.openai.com/v1" --llm-base-url
      r_ask_secret key "LLM API key" --llm-api-key
      ;;
  esac
  base="${base%/}"

  L_MODELS=""
  if [[ "${RAGGIE_SKIP_PROBE:-0}" == 1 ]]; then
    r_warn "LLM probe skipped (--skip-probe)"
  elif ! raggie_llm_probe "$base" "$key"; then
    if ! { r_can_prompt && r_confirm "LLM probe failed. Use this endpoint anyway?"; }; then
      r_die "LLM probe failed; nothing was changed (check URL/key, or pass --skip-probe)"
    fi
  fi
  local first
  first="$(printf '%s\n' "$L_MODELS" | grep -m1 . || true)"
  r_ask model "Chat model id" "$first" --llm-model
  if [[ -n "$L_MODELS" ]] && ! printf '%s\n' "$L_MODELS" | grep -qxF "$model"; then
    r_warn "model '$model' is not in the endpoint's /models list"
  fi

  r_env_set "$env" LLMAAS_BASE_URL "$base"
  # A keyless server still gets a non-empty value (the services require one).
  r_env_set "$env" LLMAAS_API_KEY "${key:-none}"
  r_env_set "$env" LLMAAS_CHAT_MODEL "$model"
}

raggie_llm_host() {
  if declare -F raggie_guess_host >/dev/null; then raggie_guess_host; else printf 'host.docker.internal'; fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -euo pipefail
  # shellcheck source=deploy/scripts/lib.sh
  . "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
  r_parse_flags "$@"
  if [[ "${RAGGIE_HELP:-0}" == 1 ]]; then r_usage "$0"; exit 0; fi
  root="${RAGGIE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
  [[ -f "$root/.env" ]] || r_die "$root/.env not found; run the installer (or make setup) first"
  RAGGIE_SETUP_MODE=upgrade RAGGIE_RECONFIGURE=1
  r_env_backup "$root/.env" >/dev/null
  raggie_llm_configure "$root"
  r_print_changes
fi
