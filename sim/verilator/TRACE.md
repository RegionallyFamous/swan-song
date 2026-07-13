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

Capture completed GDMA transfers from the linear ROM window into IRAM:

```sh
./sim/verilator/run.sh \
  --rom /path/to/game.wsc \
  --frames 10 \
  --event-trace build/sim/dma.csv \
  --trace-events mem \
  --trace-mem-initiator gdma \
  --trace-mem-space cart_rom_linear,iram
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

Memory filters are `--trace-mem-initiator`, `--trace-mem-access`,
`--trace-mem-address`, `--trace-mem-space`, `--trace-mem-offset`,
`--trace-mem-origin`, and `--trace-origin-pc`. Lists and ranges form unions;
different filters combine with AND and affect only `mem` events. `--trace-pc`
continues to mean completed-CPU PC, while `--trace-origin-pc` means the exact
first byte of the instruction that owns a memory transaction.

For repeatable investigations, copy `trace.example.conf` and pass it with
`--trace-config FILE`. The accepted keys are `output`, `format`, `events`,
`cpu_pc`, `vram_address`, `vram_role`, `mem_initiator`, `mem_access`,
`mem_address`, `mem_space`, `mem_offset`, `mem_origin`, and `origin_pc`.
Settings are applied in command-line order, so options after `--trace-config`
override the file. `format` is `csv` or `jsonl`; when omitted, a `.jsonl` or
`.ndjson` output suffix selects JSON Lines and all other suffixes select CSV.

## Events and schema

New traces use the provenance-aware v3 fields below. Numbers are unsigned decimal
values; inapplicable CSV fields are empty and inapplicable JSONL fields are
`null`.

`vram` is retained as concise CLI/event shorthand. WonderSwan has unified
internal RAM rather than a physically separate VRAM; these events are aligned
16-bit display reads expressed as 16-bit byte addresses.

| Field | Meaning |
| --- | --- |
| `cycle` | 36.864 MHz system cycle since reset was released |
| `event` | `cpu`, `bank`, `vram`, or `mem` |
| `physical_pc` | 20-bit CPU physical PC sampled at instruction completion |
| `cs`, `ip` | logical CPU location sampled at instruction completion |
| `address` | C0-C3 I/O register for `bank`; aligned internal-RAM byte address for `vram`; raw 20-bit bus byte address for `mem` |
| `value` | bank-register byte, or completed 16-bit memory-bus value interpreted with `byte_enable` |
| `role` | display fetch role; empty/null for other events |
| `initiator` | `cpu`, `gdma`, or `sdma` for `mem` |
| `access` | completed `read` or `write` for `mem` |
| `byte_enable` | raw two-bit logical bus lane mask, 0-3; zero is valid for prefetch reads |
| `space` | `iram`, `cart_sram`, `cart_rom0`, `cart_rom1`, `cart_rom_linear`, `boot_rom`, `unmapped`, or `absent_sram` |
| `mapped_offset` | exact resolved byte offset within the backing space, including address bit 0; cartridge offsets include the active mask; null for unmapped/absent SRAM |
| `instruction_id` | monotonic CPU instruction-chain identity when `origin_status=exact` |
| `origin_pc` | first byte of the owning instruction, including its first prefix, when exact |
| `origin_status` | `exact`, `unattributed` for CPU prefetch/IRQ traffic, or `not_applicable` for DMA |

`cpu` is sampled on the instruction-complete pulse. `bank` reports actual
post-mux writes to cartridge bank registers C0-C3 and de-duplicates a write
level that spans adjacent system clocks. `vram` reports active graphics RAM
arbiter issue slots on the system clock; sound-RAM and completed/idle
background slots are excluded by the RTL tap.

`mem` is a completed transaction, not a sampled request level. The RTL latches
the one-clock CPU/DMA request and resolved mapping, then captures returned data
at the core's two-edge read latency. Writes retain their issued value. CPU-side
tags distinguish future-instruction prefetch and interrupt servicing from data
owned by a decoded instruction; the logger never guesses ownership from the
nearest instruction-complete event.

The raw 20-bit address and resolved offset are both intentional. The mapper's
ROM0, ROM1, and linear windows can reach the same storage byte through different
bank registers. BIOS visibility takes precedence, and absent SRAM remains
distinct from the core's mono unmapped range. These rules match the [WSdev
memory map](https://ws.nesdev.org/wiki/Memory_map), [WSdev mapper
registers](https://ws.nesdev.org/wiki/Mapper), and pinned Mesen [address-to-ROM
conversion](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsMemoryManager.cpp#L440-L456).

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

The seven-column schema is v1 and the role-aware eight-column schema is v2.
`verify_trace.py` accepts both exact legacy headers; assertions requiring
missing role or provenance data fail explicitly. V3 appends the eight memory
fields without changing the first eight columns. JSONL contains the same v3
properties, although the standalone verifier currently validates CSV only.

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

`make regression` runs that unit test plus explicit v1/v2/v3 verifier fixtures,
requires all six display-role encodings and exact CPU memory origins from a
translated open ROM, and generates temporary bank and WSC GDMA probes. The
GDMA probe runtime-verifies linear-ROM and IRAM mapping with the ordered
completed chain `ROM 0x0100 -> IRAM 0x4000` and `ROM 0x0102 -> IRAM 0x4002`,
including known values and mapped offsets. SRAM, ROM0, ROM1, BIOS, and
absent-SRAM formulas are RTL-reviewed but do not yet have dedicated runtime
probes.
Generated ROMs remain under `build/` and are never checked in.
