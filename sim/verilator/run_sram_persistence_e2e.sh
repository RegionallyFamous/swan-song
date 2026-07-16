#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_PARENT="$ROOT/build/sim/regression"
BUILD="$BUILD_PARENT/sram-persistence-e2e"
SIM="$ROOT/build/sim/obj_dir/VSwanTop"
BUNDLE="$BUILD/bundle"
LOCK="$BUILD.lock"

fail() {
  echo "SRAM persistence regression failed: $*" >&2
  exit 1
}

require_clean_output() {
  local output="$1"
  if [[ -e "$output" || -L "$output" || -e "$output.tmp" || -L "$output.tmp" ]]; then
    fail "refusing stale output path: $output"
  fi
}

if [[ ! -x "$SIM" ]]; then
  echo "translated SwanTop simulator is unavailable: $SIM" >&2
  exit 2
fi

mkdir -p "$BUILD_PARENT"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "another SRAM persistence regression owns the exclusive lock: $LOCK" >&2
  exit 2
fi
release_lock() {
  rmdir "$LOCK" || echo "could not release SRAM persistence lock: $LOCK" >&2
}
trap release_lock EXIT
trap 'exit 130' HUP INT TERM

rm -rf "$BUILD"
# The exclusive sibling lock makes this freshly-created directory the sole
# output namespace for this invocation. Every simulator output below must also
# be absent before use, so deterministic content can never certify a stale run.
mkdir "$BUILD"
python3 "$ROOT/sim/verilator/generate_sram_persistence_probes.py" \
  "$BUNDLE" >/dev/null
python3 "$ROOT/sim/verilator/generate_sram_persistence_probes.py" \
  "$BUNDLE" --verify >/dev/null

for model in ws wsc; do
  for save_type in 03 04 05; do
    rom="$BUNDLE/sram_type${save_type}_persistence.${model}"
    statuses=(0x11 0x22 0x21)
    generations=(0x1357 0x2468 0x1357)
    previous_save=""
    for boot in 0 1 2; do
      boot_number=$((boot + 1))
      save="$BUILD/${model}-type${save_type}-boot${boot_number}.sav"
      frames="$BUILD/${model}-type${save_type}-boot${boot_number}-frames"
      require_clean_output "$save"
      args=(
        --rom "$rom"
        --max-cycles 20000
        --expect-iram-byte "0x0400=${statuses[$boot]}"
        --sram-out "$save"
        --out "$frames"
      )
      if [[ -n "$previous_save" ]]; then
        args+=(--sram-in "$previous_save")
      fi
      "$SIM" "${args[@]}" >/dev/null
      python3 "$ROOT/sim/verilator/verify_sram_persistence_save.py" \
        "$save" \
        --save-type "0x${save_type}" \
        --model "$model" \
        --generation "${generations[$boot]}" \
        --status "${statuses[$boot]}" >/dev/null
      [[ ! -e "$save.tmp" && ! -L "$save.tmp" ]] || \
        fail "simulator retained temporary output: $save.tmp"
      previous_save="$save"
    done
  done
done

# Exercise the probe's corrupt-save branch through translated RTL. The exact
# failure output must preserve the imported bytes except for the published
# status/type/model tuple. A caller waiting for a success status must instead
# time out without publishing any output.
NEGATIVE="$BUILD/negative-imports"
mkdir -p "$NEGATIVE"
negative_rom="$BUNDLE/sram_type03_persistence.ws"
valid_import="$BUILD/ws-type03-boot1.sav"
corrupt_import="$NEGATIVE/corrupt-pattern.sav"
cp "$valid_import" "$corrupt_import"
printf '\200' | dd of="$corrupt_import" bs=1 seek=256 conv=notrunc 2>/dev/null
if cmp -s "$valid_import" "$corrupt_import"; then
  fail "corrupt-import fixture did not change"
fi

failure_output="$NEGATIVE/corrupt-reported-failure.sav"
require_clean_output "$failure_output"
"$SIM" \
  --rom "$negative_rom" \
  --max-cycles 20000 \
  --expect-iram-byte 0x0400=0xee \
  --sram-in "$corrupt_import" \
  --sram-out "$failure_output" \
  --out "$NEGATIVE/corrupt-failure-frames" >/dev/null
python3 "$ROOT/sim/verilator/verify_sram_persistence_save.py" \
  "$failure_output" \
  --save-type 0x03 \
  --model ws \
  --failure-from "$corrupt_import" >/dev/null

invalid_generation_import="$NEGATIVE/invalid-generation.sav"
cp "$valid_import" "$invalid_generation_import"
printf '\231\231' | dd \
  of="$invalid_generation_import" bs=1 seek=2 conv=notrunc 2>/dev/null
invalid_generation_output="$NEGATIVE/invalid-generation-failure.sav"
require_clean_output "$invalid_generation_output"
"$SIM" \
  --rom "$negative_rom" \
  --max-cycles 20000 \
  --expect-iram-byte 0x0400=0xee \
  --sram-in "$invalid_generation_import" \
  --sram-out "$invalid_generation_output" \
  --out "$NEGATIVE/invalid-generation-frames" >/dev/null
python3 "$ROOT/sim/verilator/verify_sram_persistence_save.py" \
  "$invalid_generation_output" \
  --save-type 0x03 \
  --model ws \
  --failure-from "$invalid_generation_import" >/dev/null

run_rejected_import() {
  local name="$1"
  local input="$2"
  local expected_error="$3"
  local output="$NEGATIVE/${name}-must-not-exist.sav"
  local log="$NEGATIVE/${name}.stderr"
  require_clean_output "$output"
  if "$SIM" \
    --rom "$negative_rom" \
    --max-cycles 20000 \
    --expect-iram-byte 0x0400=0x22 \
    --sram-in "$input" \
    --sram-out "$output" \
    --out "$NEGATIVE/${name}-frames" >/dev/null 2>"$log"; then
    fail "$name import unexpectedly succeeded"
  fi
  if [[ -e "$output" || -L "$output" || -e "$output.tmp" || -L "$output.tmp" ]]; then
    fail "$name import published an output despite failure"
  fi
  if ! grep -F "$expected_error" "$log" >/dev/null; then
    sed -n '1,20p' "$log" >&2
    fail "$name import failed for an unexpected reason"
  fi
}

run_rejected_import \
  corrupt-expected-success "$corrupt_import" \
  "without the expected IRAM byte write"

truncated_import="$NEGATIVE/truncated.sav"
cp "$valid_import" "$truncated_import"
truncate -s 131071 "$truncated_import"
run_rejected_import truncated "$truncated_import" "must be exactly 131072 bytes"

oversized_import="$NEGATIVE/oversized.sav"
cp "$valid_import" "$oversized_import"
printf '\000' >>"$oversized_import"
run_rejected_import oversized "$oversized_import" "exceeds 131072-byte limit"

echo "PASS translated SwanTop SRAM persistence (fresh exclusive run, 18 positive launches, corrupt/invalid-generation status, exact-size rejection, fail-without-output)"
