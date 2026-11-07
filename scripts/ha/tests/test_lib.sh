#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Unit tests for scripts/ha/lib.sh tool lookup (no cluster, no Docker).
#   bash scripts/ha/tests/test_lib.sh
# shellcheck source-path=SCRIPTDIR/..
set -uo pipefail

HA="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../lib.sh
. "$HA/lib.sh"

failures=0
tests=0
eq() { # eq <name> <expected> <actual>
  tests=$((tests + 1))
  if [[ "$2" != "$3" ]]; then
    failures=$((failures + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3"
  fi
}
has() { [[ "$2" == *"$1"* ]] && echo yes || echo no; }

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/path" "$T/gopath/bin" "$T/empty"
fake() { printf '#!/bin/sh\necho "%s $*" >>"%s/calls"\n' "$1" "$T" >"$2" && chmod +x "$2"; }
fake docker "$T/path/docker"
fake kubeconform "$T/path/kubeconform"
fake kube-linter "$T/gopath/bin/kube-linter"
sys="$(dirname "$(command -v sh)"):$(dirname "$(command -v dirname)")"

# ── ha_tool: PATH first, then $GOPATH/bin, else fail with an install hint ───
eq tool-path "$T/path/kubeconform" "$(PATH="$T/path:$sys" GOBIN="" GOPATH="$T/gopath" ha_tool kubeconform)"
eq tool-gopath "$T/gopath/bin/kube-linter" "$(PATH="$T/path:$sys" GOBIN="" GOPATH="$T/gopath" ha_tool kube-linter)"
eq tool-gobin "$T/gopath/bin/kube-linter" "$(PATH="$T/path:$sys" GOBIN="$T/gopath/bin" GOPATH="$T/empty" ha_tool kube-linter)"

err="$( (PATH="$T/path:$sys" GOBIN="" GOPATH="$T/empty" ha_tool kube-linter) 2>&1)"
eq tool-missing-fails 1 "$( (PATH="$T/path:$sys" GOBIN="" GOPATH="$T/empty" ha_tool kube-linter) >/dev/null 2>&1; echo $?)"
eq tool-missing-hint yes "$(has "go install golang.stackrox.io/kube-linter/cmd/kube-linter@$KUBE_LINTER_VERSION" "$err")"
err="$( (PATH="$T/empty:$sys" GOBIN="" GOPATH="$T/empty" ha_tool kubeconform) 2>&1)"
eq tool-missing-hint-kubeconform yes \
  "$(has "go install github.com/yannh/kubeconform/cmd/kubeconform@$KUBECONFORM_VERSION" "$err")"
eq never-docker "" "$(grep docker "$T/calls" 2>/dev/null)"
# validate-chart.sh must never fall back to Docker.
eq validate-chart-no-docker "" "$(grep -nE '(^|[^-])docker( |$)' "$HA/validate-chart.sh" | grep -v '^[0-9]*: *#')"

printf '%d tests, %d failed\n' "$tests" "$failures"
((failures == 0))
