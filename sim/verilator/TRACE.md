# Structured simulator traces

The Verilator harness has two independent trace paths. `--trace FILE.vcd`
captures a conventional whole-design waveform. `--event-trace FILE` captures a
smaller deterministic stream intended for ROM analysis and text-renderer work.

## Quick start

Capture bank-register writes and GPU VRAM fetches as CSV:

```sh
./sim/verilator/run.sh \
  --rom /path/to/game.wsc \
  --frames 10 \
  --event-trace build/sim/game.csv \
  --trace-events bank,vram
```

Capture completed CPU instructions within an inclusive physical address range
as JSON Lines:

```sh
./sim/verilator/run.sh \
  --rom /path/to/game.wsc \
  --frames 10 \
  --event-trace build/sim/game.jsonl \
  --trace-events cpu \
  --trace-pc 0x80000-0x8ffff
```

The 20-bit physical PC is `(CS << 4) + IP`, modulo 1 MiB. `--trace-pc` filters
only `cpu` events; bank and VRAM events remain visible, which makes a mixed
trace useful even when instruction logging is tightly scoped.

For repeatable investigations, copy `trace.example.conf` and pass it with
`--trace-config FILE`. The accepted keys are `output`, `format`, `events`, and
`cpu_pc`. Settings are applied in command-line order, so options after
`--trace-config` override the file. `format` is `csv` or `jsonl`; when omitted,
a `.jsonl` or `.ndjson` output suffix selects JSON Lines and all other suffixes
select CSV.

## Events and schema

Every record uses the stable fields below. Numbers are unsigned decimal values;
inapplicable CSV fields are empty and inapplicable JSONL fields are `null`.

| Field | Meaning |
| --- | --- |
| `cycle` | 36.864 MHz system cycle since reset was released |
| `event` | `cpu`, `bank`, or `vram` |
| `physical_pc` | 20-bit CPU physical PC sampled at instruction completion |
| `cs`, `ip` | logical CPU location sampled at instruction completion |
| `address` | C0-C3 I/O register for `bank`; 16-bit GPU VRAM address for `vram` |
| `value` | byte written to a C0-C3 bank register |

`cpu` is sampled on the instruction-complete pulse. `bank` reports actual
post-mux writes to cartridge bank registers C0-C3 and de-duplicates a write
level that spans adjacent system clocks. `vram` reports each graphics RAM
arbiter issue slot on the system clock, including character/tile fetches;
sound-RAM slots are excluded by the RTL tap.

The structured trace is simulation-only and does not imply Pocket hardware
behavior. A model translated without the debug tap ports still builds and runs,
but requesting `--event-trace` fails explicitly instead of producing an empty
or misleading file.

## Parser/serializer test

```sh
c++ -std=c++17 -Wall -Wextra -Werror \
  sim/verilator/trace_logger_test.cpp \
  -o build/trace_logger_test
./build/trace_logger_test
```

`make regression` runs that unit test, validates CPU and VRAM events from a
translated open ROM, and generates a temporary 64 KiB probe that writes C0-C3.
`verify_trace.py` checks the schema and event fields and requires that all four
bank-register addresses were observed. The generated ROM remains under
`build/` and is never checked in.
