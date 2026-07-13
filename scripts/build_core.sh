#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUARTUS_SH="${QUARTUS_SH:-quartus_sh}"

command -v "$QUARTUS_SH" >/dev/null || {
  echo "quartus_sh not found; install Quartus Prime Lite 21.1.1 on Linux or Windows" >&2
  exit 127
}

cd "$ROOT/src/fpga"
# Never accept an RBF left behind by an earlier compile as this run's output.
rm -f output_files/ap_core.rbf
"$QUARTUS_SH" --flow compile ap_core

test -s output_files/ap_core.rbf || {
  echo "Quartus completed without output_files/ap_core.rbf" >&2
  exit 1
}

echo "$ROOT/src/fpga/output_files/ap_core.rbf"
