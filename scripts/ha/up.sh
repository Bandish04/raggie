#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Bring up the Raggie HA profile on a local kind cluster (3 workers / 3 zones):
#   kind cluster -> CloudNativePG operator -> local images (kind load) ->
#   generated secrets -> offline LLM + embeddings -> helm install values-ha +
#   values-kind (CNPG 3 instances, Valkey Sentinel x3, Qdrant x3, apps >= 2).
#
#   scripts/ha/up.sh            # build missing images, create/upgrade everything
#   BUILD=1 scripts/ha/up.sh    # rebuild all images first
#   scripts/ha/down.sh          # delete the cluster
#
# Needs docker, kubectl, helm, openssl, and kind (or go: `go run` pins it).
# Budget roughly 4 CPU / 6 GB for the cluster (values-kind.yaml fits an
# ubuntu-latest runner; .github/workflows/ha-chaos.yml runs it weekly).
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need docker
need kubectl
need helm
need openssl

# image|context|extra docker build args
IMAGES=(
  "raggie/edge:dev|services/edge|"
  "raggie/mockllm:dev|services/edge|-f services/edge/Dockerfile.mockllm"
  "raggie/control-plane:dev|services/control-plane|"
  "raggie/workers:dev|services/workers|"
  "raggie/web:dev|web|"
  "raggie-embeddings:slim|services/embeddings|--build-arg EMBEDDINGS_BAKE=sparse"
)

build_images() {
  local spec image ctx args
  for spec in "${IMAGES[@]}"; do
    IFS='|' read -r image ctx args <<<"$spec"
    if [[ "${BUILD:-0}" == "1" ]] || ! docker image inspect "$image" >/dev/null 2>&1; then
      log "docker build $image"
      # shellcheck disable=SC2086
      docker build -t "$image" $args "$REPO_ROOT/$ctx"
    fi
  done
}

create_cluster() {
  if kind_cmd get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
    log "kind cluster $CLUSTER_NAME exists"
  else
    log "creating kind cluster $CLUSTER_NAME ($KIND_NODE_IMAGE)"
    kind_cmd create cluster --name "$CLUSTER_NAME" --image "$KIND_NODE_IMAGE" \
      --config "$HA_DIR/kind-config.yaml" --wait 120s
  fi
}

load_images() {
  local spec image
  for spec in "${IMAGES[@]}"; do
    image="${spec%%|*}"
    log "kind load $image"
    kind_cmd load docker-image "$image" --name "$CLUSTER_NAME" >/dev/null
  done
}

install_cnpg() {
  log "CloudNativePG operator $CNPG_VERSION"
  kubectl --context "kind-$CLUSTER_NAME" apply --server-side --force-conflicts -f \
    "https://github.com/cloudnative-pg/cloudnative-pg/releases/download/v${CNPG_VERSION}/cnpg-${CNPG_VERSION}.yaml" >/dev/null
  kubectl --context "kind-$CLUSTER_NAME" -n cnpg-system rollout status deploy/cnpg-controller-manager --timeout=180s
}

hex() { openssl rand -hex "$1"; }

create_secrets() {
  kubectl --context "kind-$CLUSTER_NAME" create namespace "$NAMESPACE" --dry-run=client -o yaml \
    | kubectl --context "kind-$CLUSTER_NAME" apply -f - >/dev/null
  if ! kctl get secret raggie-secrets >/dev/null 2>&1; then
    log "generating raggie-secrets"
    kctl create secret generic raggie-secrets \
      --from-literal=JWT_SECRET="$(hex 32)" \
      --from-literal=WIDGET_TOKEN_SECRET="$(hex 32)" \
      --from-literal=INTERNAL_API_SECRET="$(hex 32)" \
      --from-literal=SETUP_TOKEN="$(hex 32)" \
      --from-literal=METRICS_TOKEN="$(hex 32)" \
      --from-literal=QDRANT_API_KEY="$(hex 32)" \
      --from-literal=REDIS_PASSWORD="$(hex 24)" \
      --from-literal=S3_ACCESS_KEY="raggie-kind" \
      --from-literal=S3_SECRET_KEY="$(hex 24)" \
      --from-literal=LLMAAS_API_KEY="mock" >/dev/null
  fi
  if ! kctl get secret raggie-chaos-admin >/dev/null 2>&1; then
    kctl create secret generic raggie-chaos-admin \
      --from-literal=email="chaos-admin@example.com" \
      --from-literal=password="Chaos-$(hex 12)-Aa1!" >/dev/null
  fi
}

install_chart() {
  log "offline LLM/embeddings upstream + chaos driver access"
  kctl create configmap mock-embeddings --from-file=mock_embeddings.py="$HA_DIR/mock_embeddings.py" \
    --dry-run=client -o yaml | kctl apply -f - >/dev/null
  kctl apply -f "$HA_DIR/manifests/mock-embeddings.yaml" -f "$HA_DIR/manifests/chaos-access.yaml" >/dev/null
  helm repo add qdrant https://qdrant.github.io/qdrant-helm >/dev/null 2>&1 || true
  helm dependency build "$CHART_DIR" >/dev/null
  log "helm upgrade --install $RELEASE (values-ha + values-kind)"
  helm --kube-context "kind-$CLUSTER_NAME" upgrade --install "$RELEASE" "$CHART_DIR" -n "$NAMESPACE" \
    -f "$CHART_DIR/values-ha.yaml" -f "$HA_DIR/values-kind.yaml" \
    --wait --timeout "${HELM_TIMEOUT:-20m}"
}

main() {
  build_images
  create_cluster
  load_images
  install_cnpg
  create_secrets
  install_chart
  kctl get pods -o wide
  log "ready: scripts/ha/chaos.sh runs the failure scenarios"
}

main "$@"
