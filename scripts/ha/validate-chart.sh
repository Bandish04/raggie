#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Static validation of deploy/helm/raggie (no cluster needed):
#   helm lint + helm template for both profiles and option variants,
#   kubeconform against Kubernetes ${K8S_SCHEMA_VERSION} (+ CRD catalog for CNPG/KEDA),
#   kube-linter, render-time guards (unsafe ha combinations must fail),
#   widget copy drift.
# kubeconform and kube-linter must be native binaries (PATH or the Go bin dir);
# the script fails with the install command when one is missing. It never runs
# Docker. OUT_DIR keeps the rendered manifests (default: mktemp).
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need helm
KUBECONFORM="$(ha_tool kubeconform)"
KUBE_LINTER="$(ha_tool kube-linter)"

kubeconform_run() { # FILE (inside OUT_DIR)
  "$KUBECONFORM" -strict -summary -kubernetes-version "$K8S_SCHEMA_VERSION" \
    -schema-location default \
    -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
    -cache "$OUT_DIR/.kubeconform-cache" "$OUT_DIR/$1"
}

kube_linter_run() { # FILE (inside OUT_DIR)
  "$KUBE_LINTER" lint "$OUT_DIR/$1"
}

OUT_DIR="${OUT_DIR:-$(mktemp -d)}"
mkdir -p "$OUT_DIR"
fail=0

"$HA_DIR/sync-widget.sh" --check || fail=1

log "helm dependency build"
helm repo add qdrant https://qdrant.github.io/qdrant-helm >/dev/null 2>&1 || true
helm dependency build "$CHART_DIR" >/dev/null

single=(-f "$CHART_DIR/values-single.yaml")
ha=(-f "$CHART_DIR/values-ha.yaml")
# name|values...
variants=(
  "single|${single[*]}"
  "ha|${ha[*]}"
  "ha-keda-pooler-legacybackup|${ha[*]} --set keda.enabled=true,keda.edge.enabled=true,keda.ingestion.enabled=true,keda.eval.enabled=true,postgresql.cnpg.pooler.enabled=true,postgresql.cnpg.backup.method=barmanObjectStore,valkey.haproxy.enabled=true"
  "ha-cloud-embeddings-mockllm|${ha[*]} --set embeddingsGateway.provider=openai_compatible,embeddingsGateway.upstreamBaseUrl=https://emb.example.com/v1,embeddingsGateway.rerankerProvider=none,embeddingsGateway.existingSecret=raggie-embeddings,mockLLM.enabled=true,networkPolicy.egress.cloudEmbeddings.cidrs={203.0.113.0/24}"
  "single-external-datastores|${single[*]} --set postgresql.mode=external,postgresql.external.host=db.example.com,postgresql.external.existingSecret=pg,valkey.mode=external,valkey.external.url=redis://redis.example.com:6379,vectordb.mode=external,vectordb.url=http://qdrant.example.com:6333,s3.mode=external,s3.external.endpoint=s3.example.com,s3.existingSecret=s3"
  "kind|${ha[*]} -f $HA_DIR/values-kind.yaml"
  "single-ingress-acme|${single[*]} --set ingress.enabled=true,ingress.clusterIssuer=letsencrypt"
)

for v in "${variants[@]}"; do
  name="${v%%|*}"
  # shellcheck disable=SC2206
  args=(${v#*|})
  log "lint + template: $name"
  if ! helm lint "$CHART_DIR" "${args[@]}" >"$OUT_DIR/$name.lint.txt" 2>&1; then
    cat "$OUT_DIR/$name.lint.txt"; fail=1; continue
  fi
  helm template "$RELEASE" "$CHART_DIR" -n "$NAMESPACE" --skip-tests "${args[@]}" >"$OUT_DIR/$name.yaml" || { fail=1; continue; }
done

log "render checks"
render_check() { # want|absent NAME PATTERN DESCRIPTION
  local hit=no
  grep -q -- "$3" "$OUT_DIR/$2.yaml" 2>/dev/null && hit=yes
  if [[ ($1 == want && $hit == yes) || ($1 == absent && $hit == no) ]]; then
    printf '  ok  %s\n' "$4"
  else
    warn "render check failed: $4"; fail=1
  fi
}
render_check want single "QDRANT__TELEMETRY_DISABLED" "single: qdrant telemetry off"
render_check want ha "QDRANT__TELEMETRY_DISABLED" "ha: qdrant telemetry off"
render_check want ha "allow-acme-http01-solver" "ha (ingress + cert-manager issuer): ACME solver admitted"
render_check want single-ingress-acme "allow-acme-http01-solver" "single + ingress + issuer: ACME solver admitted"
render_check absent single "allow-acme-http01-solver" "single (no ingress): no ACME solver policy"
helm template "$RELEASE" "$CHART_DIR" -n "$NAMESPACE" --skip-tests "${ha[@]}" \
  --set ingress.clusterIssuer= >"$OUT_DIR/ha-ingress-no-issuer.yaml" || fail=1
render_check absent ha-ingress-no-issuer "allow-acme-http01-solver" "ingress without issuer: no ACME solver policy"
source_has() { # NAME TEMPLATE PATTERN: PATTERN occurs in that template's documents
  awk -v t="/templates/$2" -v p="$3" '
    /^# Source: / { s = (substr($0, length($0) - length(t) + 1) == t) }
    s && index($0, p) { f = 1 }
    END { exit !f }' "$OUT_DIR/$1.yaml"
}
# The migrate Job holds a session advisory lock; through a transaction pooler
# the unlock can hit another backend and leak it, so it must bypass the pooler.
pooled="ha-keda-pooler-legacybackup"
if source_has "$pooled" apps.yaml "pg-pooler-rw" &&
  source_has "$pooled" migrate-job.yaml "pg-rw" &&
  ! source_has "$pooled" migrate-job.yaml "pooler"; then
  printf '  ok  %s\n' "pooler on: apps use the pooler, migrate Job the primary"
else
  warn "render check failed: pooler on: migrate Job must connect to <cluster>-rw, apps to the pooler"; fail=1
fi

log "kubeconform (k8s ${K8S_SCHEMA_VERSION}, strict, CRDs from datreeio/CRDs-catalog)"
# Schemas are downloaded once per run and shared through the cache dir.
mkdir -p "$OUT_DIR/.kubeconform-cache"
for f in "$OUT_DIR"/*.yaml; do
  kubeconform_run "$(basename "$f")" || fail=1
done

log "kube-linter (single, ha)"
for name in single ha; do
  kube_linter_run "$name.yaml" || fail=1
done

log "render-time guards (each must fail)"
guards=(
  "ha with generated secrets|${ha[*]} --set secrets.generateDevSecret=true"
  "ha with in-chart postgres|${ha[*]} --set postgresql.mode=internal"
  "ha with standalone valkey|${ha[*]} --set valkey.mode=standalone"
  "ha with single qdrant|${ha[*]} --set vectordb.mode=single,qdrant.enabled=false"
  "sentinel without quorum|${ha[*]} --set valkey.replicas=2"
  "edge grace shorter than drain|${ha[*]} --set edge.shutdown.terminationGraceSeconds=20"
  "external s3 without secret|${ha[*]} --set s3.existingSecret="
  "no secrets at all|${single[*]} --set secrets.generateDevSecret=false"
)
for g in "${guards[@]}"; do
  name="${g%%|*}"
  # shellcheck disable=SC2206
  args=(${g#*|})
  if helm template "$RELEASE" "$CHART_DIR" "${args[@]}" >/dev/null 2>&1; then
    warn "guard did not fire: $name"; fail=1
  else
    printf '  ok  %s\n' "$name"
  fi
done

[[ $fail -eq 0 ]] || die "chart validation failed (rendered manifests in $OUT_DIR)"
log "chart validation passed (rendered manifests in $OUT_DIR)"
