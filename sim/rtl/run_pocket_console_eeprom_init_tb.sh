#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$(mktemp -d "$ROOT/build/sim/pocket_console_eeprom_init_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

verilator --binary --timing --assert -Wall -Wno-fatal \
  -Wno-BLKSEQ -Wno-PROCASSINIT \
  --Mdir "$BUILD/obj_dir" \
  --top-module pocket_console_eeprom_init_tb \
  "$ROOT/src/fpga/core/pocket_console_eeprom_init.sv" \
  "$ROOT/sim/rtl/pocket_console_eeprom_init_tb.sv"

"$BUILD/obj_dir/Vpocket_console_eeprom_init_tb"
