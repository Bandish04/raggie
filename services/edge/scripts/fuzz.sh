#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Run every Go native fuzz target in the edge module, one after another.
#
#   FUZZTIME=20s scripts/fuzz.sh      # per-PR smoke run (~8 min for all targets)
#   FUZZTIME=10m scripts/fuzz.sh      # nightly deep run
#
# New crashers are written to <package>/testdata/fuzz/<Target>/ by `go test`;
# commit them so they replay as regression tests in the normal `go test` run.
# Exits non-zero if any target fails.
set -eu
cd "$(dirname "$0")/.."
FUZZTIME="${FUZZTIME:-20s}"
status=0
for pkg in $(go list ./...); do
  for target in $(go test -list '^Fuzz' "$pkg" | grep '^Fuzz' || true); do
    echo "==> $pkg $target ($FUZZTIME)"
    if ! go test -run '^$' -fuzz "^${target}\$" -fuzztime "$FUZZTIME" "$pkg"; then
      status=1
    fi
  done
done
exit "$status"
