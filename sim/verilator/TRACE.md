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

Restrict output to Screen 1 tile-data fetches in the mono 2bpp tile area:

```sh
./sim/verilator/run.sh \
  --rom /path/to/game.ws \
  --frames 10 \
  --event-trace build/sim/screen1-tiles.csv \
  --trace-events vram \
  --trace-vram-role screen1_tile \
  --trace-vram-address 0x2000-0x3fff
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

`--trace-vram-address` accepts comma-separated 16-bit addresses or inclusive
ranges. `--trace-vram-role` accepts `screen1_map`, `screen1_tile`,
`screen2_map`, `screen2_tile`, `sprite_table`, `sprite_tile`, or `all`.
Multiple address ranges form a union; address and role filters combine with
AND. Both filters affect only `vram` events, so CPU and bank events remain in a
mixed trace.

For repeatable investigations, copy `trace.example.conf` and pass it with
`--trace-config FILE`. The accepted keys are `output`, `format`, `events`,
`cpu_pc`, `vram_address`, and `vram_role`. Settings are applied in command-line
order, so options after `--trace-config` override the file. `format` is `csv`
or `jsonl`; when omitted, a `.jsonl` or `.ndjson` output suffix selects JSON
Lines and all other suffixes select CSV.

## Events and schema

New traces use the role-aware v2 fields below. Numbers are unsigned decimal
values; inapplicable CSV fields are empty and inapplicable JSONL fields are
`null`.

`vram` is retained as concise CLI/event shorthand. WonderSwan has unified
internal RAM rather than a physically separate VRAM; these events are aligned
16-bit display reads expressed as 16-bit byte addresses.

| Field | Meaning |
| --- | --- |
| `cycle` | 36.864 MHz system cycle since reset was released |
| `event` | `cpu`, `bank`, or `vram` |
| `physical_pc` | 20-bit CPU physical PC sampled at instruction completion |
| `cs`, `ip` | logical CPU location sampled at instruction completion |
| `address` | C0-C3 I/O register for `bank`; aligned 16-bit internal-RAM byte address for `vram` |
| `value` | byte written to a C0-C3 bank register |
| `role` | VRAM fetch role; empty/null for CPU and bank events |

`cpu` is sampled on the instruction-complete pulse. `bank` reports actual
post-mux writes to cartridge bank registers C0-C3 and de-duplicates a write
level that spans adjacent system clocks. `vram` reports active graphics RAM
arbiter issue slots on the system clock; sound-RAM and completed/idle
background slots are excluded by the RTL tap.

The screen roles distinguish tile-map attribute reads from tile bitmap reads.
`sprite_table` identifies sprite-table DMA reads into the core's internal
sprite buffer, while `sprite_tile` identifies sprite bitmap reads. A role
describes an active fetch source, not a guarantee that the word contributes a
visible pixel, and the trace does not currently include the fetched word.

This split follows the [WSdev display and unified-memory
model](https://ws.nesdev.org/w/index.php?title=Display&oldid=555) and pinned
ares behavior, which reads a [screen-map word before separate tile
data](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/screen.cpp#L17-L32).
Mode-specific tile ranges are documented by [WSdev Tile
Data](https://ws.nesdev.org/w/index.php?title=Display/Tile_Data&oldid=504).

The previous seven-column CSV schema is v1. `verify_trace.py` continues to
accept its exact header, but old traces do not contain enough information for
role assertions. New writers append `role` as the eighth column; the first
seven columns retain their original order. JSONL adds the `role` property.

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

`make regression` runs that unit test, requires all six role encodings with
aligned addresses from a translated open ROM, and generates a temporary 64 KiB
probe that writes C0-C3. `verify_trace.py` accepts exact v1 and v2 CSV headers,
checks event-specific fields and range/role constraints, and requires that all
four bank-register addresses were observed. Role assertions against v1 fail
explicitly. The generated ROM remains under `build/` and is never checked in.
