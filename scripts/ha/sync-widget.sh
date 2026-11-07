#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copy widget/embed.js into the chart (Helm can only read files inside the
# chart directory). `--check` exits 1 when the copy drifted (CI gate).
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

src="$REPO_ROOT/widget/embed.js"
dst="$CHART_DIR/files/widget/embed.js"
if [[ "${1:-}" == "--check" ]]; then
  cmp -s "$src" "$dst" || die "$dst drifted from widget/embed.js; run scripts/ha/sync-widget.sh"
  log "chart widget copy is in sync"
else
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
  log "synced $dst"
fi
