#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# TLS contract of the Kustomize overlays (no cluster, no Docker): the prod
# overlay terminates TLS on both Ingresses (cert-manager) with the SSE
# annotations, and its ConfigMap matches the https hosts; dev stays plain HTTP.
#
#   bash deploy/k8s/tests/tls_test.sh      # also run by `make kustomize-validate`
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
failures=0

for overlay in dev prod; do
  kubectl kustomize --load-restrictor LoadRestrictionsNone \
    "$REPO_ROOT/deploy/k8s/overlays/$overlay" >"$TMP/$overlay.yaml"
done

# field OVERLAY KIND NAME JSONPATH: one field of one rendered object, read offline
# (`kubectl label --local` evaluates the jsonpath without contacting a cluster).
field() {
  KUBECONFIG=/dev/null kubectl label --local -f "$TMP/$1.yaml" raggie.io/probe=1 \
    -o jsonpath="{.kind}/{.metadata.name}={$4}{\"\n\"}" | sed -n "s|^$2/$3=||p"
}
expect() { # expect DESCRIPTION GOT WANT
  if [[ "$2" == "$3" ]]; then
    printf '  ok   %s\n' "$1"
  else
    printf '  FAIL %s: got %q, want %q\n' "$1" "$2" "$3" >&2
    failures=$((failures + 1))
  fi
}

ISSUER='.metadata.annotations.cert-manager\.io/cluster-issuer'
NGINX='.metadata.annotations.nginx\.ingress\.kubernetes\.io'

echo "prod overlay"
for ing in raggie-public raggie-admin; do
  host="$(field prod Ingress "$ing" .spec.rules[0].host)"
  expect "$ing has a host" "${host:+set}" set
  expect "$ing cert-manager issuer" "$(field prod Ingress "$ing" "$ISSUER")" letsencrypt
  expect "$ing tls host = rule host" "$(field prod Ingress "$ing" .spec.tls[0].hosts[0])" "$host"
  expect "$ing tls secret" "$(field prod Ingress "$ing" .spec.tls[0].secretName)" "$ing-tls"
  expect "$ing SSE proxy-buffering" "$(field prod Ingress "$ing" "$NGINX/proxy-buffering")" off
  expect "$ing SSE read timeout" "$(field prod Ingress "$ing" "$NGINX/proxy-read-timeout")" 3600
done
expect "raggie-public request buffering" \
  "$(field prod Ingress raggie-public "$NGINX/proxy-request-buffering")" off
expect "raggie-public send timeout" \
  "$(field prod Ingress raggie-public "$NGINX/proxy-send-timeout")" 3600

public_host="$(field prod Ingress raggie-public .spec.rules[0].host)"
admin_host="$(field prod Ingress raggie-admin .spec.rules[0].host)"
expect "COOKIE_SECURE" "$(field prod ConfigMap raggie-config .data.COOKIE_SECURE)" true
expect "ENABLE_HSTS" "$(field prod ConfigMap raggie-config .data.ENABLE_HSTS)" true
expect "PUBLIC_WEB_URL = admin https host" \
  "$(field prod ConfigMap raggie-config .data.PUBLIC_WEB_URL)" "https://$admin_host"
expect "WIDGET_EMBED_BASE_URL = public https host" \
  "$(field prod ConfigMap raggie-config .data.WIDGET_EMBED_BASE_URL)" "https://$public_host"

# default-deny-ingress would block ingress-nginx -> cert-manager HTTP-01 solver.
SOLVER=allow-acme-http01-solver
expect "ACME solver pods selected" "$(field prod NetworkPolicy "$SOLVER" \
  '.spec.podSelector.matchLabels.acme\.cert-manager\.io/http01-solver')" true
expect "ACME solver reachable from ingress-nginx" "$(field prod NetworkPolicy "$SOLVER" \
  '.spec.ingress[0].from[0].namespaceSelector.matchLabels.kubernetes\.io/metadata\.name')" \
  ingress-nginx
expect "ACME solver port" "$(field prod NetworkPolicy "$SOLVER" .spec.ingress[0].ports[0].port)" 8089

echo "dev overlay (plain HTTP)"
for ing in raggie-public raggie-admin; do
  expect "$ing has no tls" "$(field dev Ingress "$ing" .spec.tls)" ""
  expect "$ing has no issuer" "$(field dev Ingress "$ing" "$ISSUER")" ""
done
expect "no HSTS in dev" "$(field dev ConfigMap raggie-config .data.ENABLE_HSTS)" ""

if ((failures)); then
  echo "$failures TLS check(s) failed" >&2
  exit 1
fi
echo "all TLS checks passed"
