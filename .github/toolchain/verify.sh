#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
TOOLCHAIN="$ROOT/.github/toolchain"

EXPECTED_VERILATOR_IMAGE="verilator/verilator@sha256:c531ae1e5da8e7293a2bd6793060c2bf484dac358746e69bcc3e689ec265b299"
EXPECTED_GHDL_IMAGE="ghdl/ghdl@sha256:8b3ec37c3873b2eee9387759e66c50830c15ae5b7b533badaa97ce007a0f8022"
EXPECTED_VERILATOR_VERSION="Verilator 5.050 2026-07-01 rev v5.050"
EXPECTED_VERILATOR_REVISION="848d926ebd4addacacd294dc84e35d9d4ae8078c"
EXPECTED_CXX_VERSION="g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"
EXPECTED_GHDL_VERSION="GHDL 6.0.0 (6.0.0.r0.ge589c698c) [Dunoon edition]"

export VERILATOR_IMAGE="${VERILATOR_IMAGE:-$EXPECTED_VERILATOR_IMAGE}"
export GHDL_IMAGE="${GHDL_IMAGE:-$EXPECTED_GHDL_IMAGE}"

if [[ "$VERILATOR_IMAGE" != "$EXPECTED_VERILATOR_IMAGE" ]]; then
  echo "VERILATOR_IMAGE must equal $EXPECTED_VERILATOR_IMAGE" >&2
  exit 2
fi
if [[ "$GHDL_IMAGE" != "$EXPECTED_GHDL_IMAGE" ]]; then
  echo "GHDL_IMAGE must equal $EXPECTED_GHDL_IMAGE" >&2
  exit 2
fi
command -v docker >/dev/null || {
  echo "docker is required for the pinned HDL toolchain" >&2
  exit 127
}

docker pull --quiet "$VERILATOR_IMAGE" >/dev/null
docker pull --quiet "$GHDL_IMAGE" >/dev/null

verilator_version="$("$TOOLCHAIN/verilator" --version)"
if [[ "$verilator_version" != "$EXPECTED_VERILATOR_VERSION" ]]; then
  echo "unexpected Verilator version: $verilator_version" >&2
  exit 1
fi

verilator_revision="$(docker image inspect "$VERILATOR_IMAGE" --format \
  '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
if [[ "$verilator_revision" != "$EXPECTED_VERILATOR_REVISION" ]]; then
  echo "unexpected Verilator source revision: $verilator_revision" >&2
  exit 1
fi

cxx_version="$("$TOOLCHAIN/cxx" --version | sed -n '1p')"
if [[ "$cxx_version" != "$EXPECTED_CXX_VERSION" ]]; then
  echo "unexpected C++ compiler version: $cxx_version" >&2
  exit 1
fi

ghdl_output="$(docker run --rm --platform linux/amd64 "$GHDL_IMAGE" ghdl --version)"
ghdl_version="${ghdl_output%%$'\n'*}"
if [[ "$ghdl_version" != "$EXPECTED_GHDL_VERSION" ]]; then
  echo "unexpected GHDL version: $ghdl_version" >&2
  exit 1
fi

echo "$verilator_version"
echo "$cxx_version"
echo "$ghdl_version"
echo "Verilator source revision $verilator_revision"
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "NOTE: version pins verified; the container-built simulator runs in CI on Linux/amd64."
fi
