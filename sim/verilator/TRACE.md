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

Capture completed CPU instructions within a union of inclusive physical
address ranges as JSON Lines:

```sh
./sim/verilator/run.sh \
  --rom /path/to/game.wsc \
  --frames 10 \
  --event-trace build/sim/game.jsonl \
  --trace-events cpu \
  --trace-pc 0x80000-0x8ffff,0xf0000-0xfffff
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

Build confirmation-grade reports for every completed display read and every
background cell promoted into a pixel-producing buffer:

```sh
./sim/verilator/run.sh \
  --rom /path/to/game.wsc \
  --frames 10 \
  --event-trace build/sim/text.csv \
  --trace-events mem,vram,bg_cell
python3 sim/verilator/correlate_provenance.py \
  build/sim/text.csv \
  --output build/sim/text-provenance.csv \
  --fail-on-mismatch \
  --require-complete-coverage
python3 sim/verilator/correlate_bg_cells.py \
  build/sim/text.csv \
  --output build/sim/text-bg-cells.csv \
  --require-complete-coverage
```

Do not apply memory or display filters to the capture used for complete
provenance. Apply `correlate_provenance.py` output filters afterward so the
tool can reconstruct the full IRAM history. The atomic background correlator
also requires an exact, unfiltered capture. Every `bg_cell` must match a raw
Screen 1/2 fetch group; physical read-ahead that has not been promoted when the
capture ends is counted explicitly rather than mistaken for corruption.

The 20-bit physical PC is `(CS << 4) + IP`, modulo 1 MiB. `--trace-pc` accepts
one or more comma-separated inclusive `START-END` ranges and treats them as a
union. It filters only `cpu` events; bank and VRAM events remain visible, which
makes a mixed trace useful even when instruction logging is tightly scoped.

`--trace-vram-address` accepts comma-separated 16-bit addresses or inclusive
ranges. `--trace-vram-role` accepts `screen1_map`, `screen1_tile`,
`screen2_map`, `screen2_tile`, `sprite_table`, `sprite_tile`, or `all`.
Multiple address ranges form a union; address and role filters combine with
AND. Both filters affect only `vram` events, so CPU and bank events remain in a
mixed trace. They do not filter `bg_cell`; capture all three of `mem`, `vram`,
and `bg_cell` for complete atomic-cell provenance.

Memory filters are `--trace-mem-initiator`, `--trace-mem-access`,
`--trace-mem-address`, `--trace-mem-space`, `--trace-mem-offset`,
`--trace-mem-origin`, and `--trace-origin-pc`. Lists and ranges form unions;
different filters combine with AND and affect only `mem` events.
`--trace-origin-pc` accepts the same comma-separated range-union syntax as
`--trace-pc`, but means the exact first byte of the instruction that owns a
memory transaction rather than the completed-instruction PC.

For repeatable investigations, copy `trace.example.conf` and pass it with
`--trace-config FILE`. The accepted keys are `output`, `format`, `events`,
`cpu_pc`, `vram_address`, `vram_role`, `mem_initiator`, `mem_access`,
`mem_address`, `mem_space`, `mem_offset`, `mem_origin`, and `origin_pc`.
Settings are applied in command-line order, so options after `--trace-config`
override the file. `format` is `csv` or `jsonl`; when omitted, a `.jsonl` or
`.ndjson` output suffix selects JSON Lines and all other suffixes select CSV.
The `cpu_pc` and `origin_pc` config values accept the same comma-separated
inclusive range unions as their command-line counterparts.

## Events and schema

New traces use the atomic-background-aware v5 fields below. Numbers are unsigned decimal
values; inapplicable CSV fields are empty and inapplicable JSONL fields are
`null`.

`vram` is retained as concise CLI/event shorthand. WonderSwan has unified
internal RAM rather than a physically separate VRAM; these events are aligned
16-bit display reads expressed as 16-bit byte addresses.

| Field | Meaning |
| --- | --- |
| `cycle` | 36.864 MHz system cycle since reset was released |
| `event` | `cpu`, `bank`, `vram`, `mem`, or `bg_cell` |
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
| `fetch_value` | completed 16-bit display-read word for `vram` |
| `fetch_collision` | 1 when the CPU/DMA write port addressed the same IRAM word on the display-read edge; otherwise 0 |
| `bg_layer` | 1 for Screen 1 or 2 for Screen 2 on `bg_cell` |
| `map_address`, `map_value` | completed screen-map word address and value promoted for the cell |
| `map_x`, `map_y` | 0-31 map coordinates decoded from `map_address`; these are map-space coordinates, not final screen pixels |
| `tile_bank_enabled`, `tile_index` | extended tile-bank mode and resulting 10-bit tile index decoded from the map word |
| `palette`, `hflip`, `vflip` | palette and flip attributes decoded from the map word |
| `bpp`, `packed` | 2/4-bit depth and planar/packed mode used for this row |
| `tile_row` | 0-7 row after vertical-flip selection |
| `tile_row_address`, `tile_row_bytes`, `tile_row_value` | exact contributing tile row: one 16-bit word for 2bpp or both words, low word first, for 4bpp |
| `map_collision`, `tile_row_collision` | mixed-port uncertainty on the promoted map word or contributing row |

`cpu` is sampled on the instruction-complete pulse. `bank` reports actual
post-mux writes to cartridge bank registers C0-C3 and de-duplicates a write
level that spans adjacent system clocks. `vram` reports completed active
graphics IRAM reads. Address/role request metadata is delayed through the same
synchronous-RAM pipeline as `fetch_value`; sound-RAM and completed/idle
background slots are excluded. Repeated reads during the background fetch
wait state remain visible because they are real physical bus reads, not unique
logical screen cells.

Intel does not define [mixed-port read-during-write
data](https://www.intel.com/content/www/us/en/programmable/quartushelp/current/hdl/mega/mega_file_altsynch_ram_d1289e822.htm)
for this inferred dual-port RAM unless a mode is selected. A collision-marked simulator value is
useful diagnostically but is not hardware-independent evidence. The collision
bit is delayed with the request and returned word so analysis can preserve that
uncertainty rather than choosing old or new data.

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
visible pixel. V5 retains the completed fetched word, but raw physical reads
can still include pipeline or prefetch work that does not contribute a pixel.

`bg_cell` is the logical companion to those raw reads. It pulses when a
completed Screen 1 or Screen 2 fetch buffer is promoted into the buffer used by
the pixel shifter. It binds the map word to its decoded tile index, palette,
flips, format, and exact contributing tile row. The existing background engine
physically reads both aligned words around a row; in 2bpp only the word selected
by the row address can contribute, while in 4bpp both words contribute. The
event records that distinction instead of treating every raw tile read as
visible data. The 16-byte 2bpp and 32-byte 4bpp tile layouts, and therefore the
2-byte versus 4-byte row formulas, follow WSdev's
[tile-data specification](https://ws.nesdev.org/wiki/Display/Tile_Data).

This is a cell-consumption boundary, not a final-pixel assertion. A promoted
cell may still be outside a window, transparent, disabled, covered by the other
background or a sprite, or fetched for scroll prefill. The event also says
nothing by itself about glyph or character identity. `bg_cell` excludes the
sprite pipeline; sprite-table and sprite-tile activity remains available only
through the raw `vram` roles.

This split follows the [WSdev display and unified-memory
model](https://ws.nesdev.org/w/index.php?title=Display&oldid=555) and pinned
ares behavior, which reads a [screen-map word before separate tile
data](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/screen.cpp#L17-L32).
Mode-specific tile ranges are documented by [WSdev Tile
Data](https://ws.nesdev.org/w/index.php?title=Display/Tile_Data&oldid=504).

The seven-column schema is v1 and the role-aware eight-column schema is v2.
`verify_trace.py` accepts both exact legacy headers; assertions requiring
missing role or provenance data fail explicitly. V3 appends the eight memory
fields without changing the first eight columns. V4 appends `fetch_value` and
`fetch_collision`. V5 appends the 18 atomic background-cell fields without
changing the v4 prefix. JSONL contains the same v5 properties, although the
standalone verifier currently validates CSV only.

Every successful event capture also writes `FILE.manifest.json`. The manifest
records whether capture began at reset release, reached its requested frame
target, included unfiltered `mem` and `vram` history, included `bg_cell` when
requested, avoided save-state input, and can therefore use the defined zero
power-up state of IRAM. Its byte length and FNV-1a digest bind that certificate
to the exact trace file; starting a new capture at the same path invalidates
the old manifest before truncating the trace. The word-level correlator labels
coverage `complete_from_reset` only when the memory/display conditions hold.
The atomic correlator additionally requires `events.bg_cell=true` and
`complete_bg_cell_history=true`; otherwise it refuses
`--require-complete-coverage` and never treats an absent write as zero.

`correlate_provenance.py` maintains IRAM per byte, respects partial and odd
writes, preserves exact CPU origins, and pairs GDMA reads/writes only in
protocol order with matching value and byte enable. For every display read it
compares the returned word with the independently reconstructed bytes and
reports the low/high writer and any mapped ROM source. A collision produces
`unspecified_collision`, while a non-collision disagreement produces
`mismatch` and can fail the run. This proves graphics-data provenance; it does
not by itself prove that a tile index is a character code. Rasterized text can
write glyph bitmaps into preassigned canvas tiles, as documented for
[WonderWitch Shift-JIS text](https://ws.nesdev.org/wiki/WonderWitch/FreyaBIOS/Text).

`correlate_bg_cells.py` independently assembles map/tile0/tile1 groups for
Screen 1 and Screen 2, then matches each atomic cell to the newest completed
group held by that layer. The GPU continues physical prefetch while a layer is
disabled; completed groups replaced before promotion are counted as
`raw_superseded`, not FIFO-paired to a later cell. Completed or partial
read-ahead at the capture boundary is likewise reported as `raw_unpromoted` or
`raw_inflight`. Every emitted atomic cell still requires an exact group.
Crucially, the correlator snapshots each byte's writer and optional GDMA ROM
source on the raw-fetch edge, before a same-cycle or intervening IRAM write; it
never looks up the current writer at the later promotion edge. It validates the
map decode, row formula, raw addresses and values, and reports per-byte map and
contributing-row provenance. A map or contributing-row mismatch/collision
fails. In 2bpp, uncertainty on the physically fetched but non-contributing
aligned neighbor remains visible in the raw fields without tainting the cell.

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

`make regression` runs that unit test plus explicit v1/v2/v3/v4/v5 verifier
fixtures and focused byte-lane/atomic-cell correlator tests. Its translated
open-ROM captures require all six display-role encodings, exact CPU memory
origins, `bg_cell` events, and nonzero atomic-cell coverage from both screen
layers. The suite generates temporary bank and WSC GDMA probes. The
GDMA probe runtime-verifies linear-ROM and IRAM mapping with the ordered
completed chain `ROM 0x0100 -> IRAM 0x4000` and `ROM 0x0102 -> IRAM 0x4002`,
including known values and mapped offsets. SRAM, ROM0, ROM1, BIOS, and
absent-SRAM formulas are RTL-reviewed but do not yet have dedicated runtime
probes.
Generated ROMs remain under `build/` and are never checked in.

The six-frame display-provenance regression requires 78,946/78,946
non-collision physical display reads to match the complete-from-reset IRAM
scoreboard: 78,754 are tied to exact CPU writer instructions and 192 pre-enable
prefetches to the defined power-up value. Any value mismatch fails regression.
The atomic-cell gate validates 26,224 bootstrap cells across both screen layers;
the extended-range Color fixture adds 5,176 Screen 1 cells. The focused unit
test locks 2bpp/4bpp selection, simultaneous layers, collisions, superseded
prefetches, and writer-snapshot timing.
