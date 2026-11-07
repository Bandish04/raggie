#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Delete the kind cluster created by scripts/ha/up.sh (all its data included).
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
kind_cmd delete cluster --name "$CLUSTER_NAME"
