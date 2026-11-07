# SPDX-License-Identifier: Apache-2.0
# Shared helpers for scripts/ha/*.sh (sourced, not executed).
# shellcheck shell=bash disable=SC2034

HA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HA_DIR/../.." && pwd)"
CHART_DIR="$REPO_ROOT/deploy/helm/raggie"

CLUSTER_NAME="${CLUSTER_NAME:-raggie-ha}"
NAMESPACE="${NAMESPACE:-raggie}"
RELEASE="${RELEASE:-raggie}"
# A node image built for KIND_VERSION (digest from its release notes).
KIND_NODE_IMAGE="${KIND_NODE_IMAGE:-kindest/node:v1.33.4@sha256:25a6018e48dfcaee478f4a59af81157a437f15e6e140bf103f85a2e7cd0cbbf2}"
KIND_VERSION="${KIND_VERSION:-v0.30.0}"
CNPG_VERSION="${CNPG_VERSION:-1.30.1}"
K6_IMAGE="${K6_IMAGE:-grafana/k6:1.3.0@sha256:3ddc8b1a33a2c3d8edc6e99b6a762ae36cba08788463458f5e6a7703e14eb77d}"
KUBECONFORM_VERSION="${KUBECONFORM_VERSION:-v0.7.0}"
KUBE_LINTER_VERSION="${KUBE_LINTER_VERSION:-v0.8.3}"
K8S_SCHEMA_VERSION="${K8S_SCHEMA_VERSION:-1.30.0}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33mWARN\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31mERROR\033[0m %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required${2:+ ($2)}"; }

# ha_tool NAME: path of a native kubeconform/kube-linter from PATH or the Go
# bin dir; otherwise fails with the pinned install command (never Docker).
ha_tool() {
  local name=$1 pkg ver bin
  case "$name" in
    kubeconform) pkg=github.com/yannh/kubeconform/cmd/kubeconform ver=$KUBECONFORM_VERSION ;;
    kube-linter) pkg=golang.stackrox.io/kube-linter/cmd/kube-linter ver=$KUBE_LINTER_VERSION ;;
    *) die "ha_tool: unknown tool $name" ;;
  esac
  bin="$(command -v "$name" 2>/dev/null)" && { echo "$bin"; return; }
  bin="${GOBIN:-${GOPATH:-$HOME/go}/bin}/$name"
  [[ -x "$bin" ]] && { echo "$bin"; return; }
  die "$name not found: install it with \`go install $pkg@$ver\` (or a release binary on PATH)"
}

# kind from PATH, or `go run` the pinned release (no global install needed).
kind_cmd() {
  if command -v kind >/dev/null 2>&1; then
    kind "$@"
  else
    need go "or install kind: https://kind.sigs.k8s.io"
    go run "sigs.k8s.io/kind@${KIND_VERSION}" "$@"
  fi
}

kctl() { kubectl --context "kind-${CLUSTER_NAME}" -n "$NAMESPACE" "$@"; }

now() { date +%s; }

# wait_until TIMEOUT_SECONDS DESCRIPTION CMD... — poll CMD every second.
wait_until() {
  local timeout="$1" what="$2" deadline
  shift 2
  deadline=$(( $(now) + timeout ))
  until "$@" >/dev/null 2>&1; do
    if [[ $(now) -ge $deadline ]]; then
      warn "timed out after ${timeout}s waiting for: $what"
      return 1
    fi
    sleep 1
  done
}
