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
  --trace-frame-artifacts \
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

## Cross-process cartridge SRAM

The direct translated-core harness can import and atomically export the exact
cartridge SRAM capacity declared by footer types `0x01` through `0x05`:

```sh
build/sim/obj_dir/VSwanTop \
  --rom build/open-probes/sram_type03_persistence.ws \
  --max-cycles 20000 \
  --expect-iram-byte 0x0400=0x11 \
  --sram-out build/open-probes/type03.sav

build/sim/obj_dir/VSwanTop \
  --rom build/open-probes/sram_type03_persistence.ws \
  --max-cycles 20000 \
  --expect-iram-byte 0x0400=0x22 \
  --sram-in build/open-probes/type03.sav \
  --sram-out build/open-probes/type03.sav
```

`--sram-in` requires one exact 32/128/256/512 KiB regular, single-link file;
short, oversized, symlinked, hard-linked, or footer-incompatible inputs fail.
`--sram-out` is published only after the requested frame or exact IRAM write
and any controller replay have completed successfully. Import and output may
name the same save because the input is fully read before atomic replacement.
An output may not alias ROM, controller script, trace, trace manifest,
VCD, or generated frame paths.

Trace manifest v1 does not bind imported SRAM identity, so `--sram-in` and
`--event-trace` are deliberately incompatible. The normal regression uses the
repository-authored probe bundle and `run_sram_persistence_e2e.sh` to run three
separate processes for all six mono/Color type-`03`/`04`/`05` combinations.
It requires the exact `0x11`, `0x22`, then `0x21` status sequence and verifies
every byte of each resulting save. This proves the translated V30MZ,
memorymux, and mapper path; it does not replace the Pocket/APF loader/unloader,
SDRAM-wrapper, quit/relaunch, or power-cycle hardware cases.

## Deterministic controller replay

`--input-script FILE` replays complete WonderSwan controller states at exact
system cycles. It is a simulation option, not a structured-trace filter, so it
is intentionally not a key in `trace.example.conf`. The v1 input-script grammar
is line-oriented:

```text
SYSTEM_CYCLE STATE
```

Blank lines and text from `#` to the end of a line are ignored. Every other
line must contain exactly two whitespace-separated fields:

- `SYSTEM_CYCLE` is an unsigned decimal integer. Hexadecimal, signs, and
  suffixes are not accepted, and event cycles must be strictly increasing.
- `STATE` is either `none` or a comma-separated list drawn from the
  case-sensitive physical console labels `x1`, `x2`, `x3`, `x4`, `y1`, `y2`,
  `y3`, `y4`, `start`, `a`, and `b`. These are the two WonderSwan directional
  clusters and three buttons as presented to the system core, not logical
  Pocket directions or rotation-dependent aliases. Embedded spaces, unknown
  labels, empty entries, and duplicate buttons are rejected.

Each event replaces the complete controller state; it is not a press/release
delta. For example, changing `x2,a` to `a` releases `x2` and keeps `a` held.
The state persists through every gap until the next event. Before the first
event all buttons are released. A valid script must contain at least one
non-`none` state, and its final event must be `none` so the replay finishes
with every button released.
Source files are limited to 4 MiB and 65,536 parsed events.

Cycle 0 is the first 36.864 MHz system cycle after reset is released. An event
at cycle N is applied before the rising system-clock edge reported as trace
cycle N. Convert cycles to time with `seconds = cycles / 36,864,000`, or
`milliseconds = cycles / 36,864`; for example, 3,686,400 cycles is 100 ms.
This timing is exact for the simulator clock, while the game decides when it
polls the controller.

Start from the commented `input.example.input` and keep a title-specific copy
with the user's private artifacts:

```sh
mkdir -p build/private
cp sim/verilator/input.example.input build/private/title.input

./sim/verilator/run.sh \
  --rom /path/to/personally-owned-title.wsc \
  --input-script build/private/title.input \
  --frames 35 \
  --max-cycles 20000000 \
  --out build/private/title-route \
  --event-trace build/private/title-route/events.csv \
  --trace-events cpu,bank,vram,mem,bg_cell,sprite_row
```

The final release event must be earlier than `--max-cycles`; an impossible
schedule is rejected before the model runs. The run also fails if its requested
frame target is reached before every input event has been applied. A failed or
incomplete attempt does not receive a success manifest.

For a successful event trace, `FILE.manifest.json` contains an optional
`input_script` object with the v1 schema name, raw source byte size and FNV-1a
digest, normalized schedule digest, declared and applied event counts,
completion state, and released final state. The raw binding detects changes to
comments and formatting; the normalized binding records parsed cycles and full
button masks. As with the ROM, built-in Open IPL, and trace digests, these are
deterministic stale-artifact checks rather than cryptographic authentication.

Before treating a private route and trace as one evidence bundle, verify that
the exact script still matches the success manifest and trace bytes:

```sh
python3 sim/verilator/verify_input_script_manifest.py \
  build/private/title-route/events.csv \
  build/private/title.input
```

This generic verifier reparses the v1 grammar independently, checks both script
identities and all completion fields, and rejects a changed script, trace, or
manifest.

Regression uses the same route to exercise interrupt-facing input semantics.
A build-generated Color ROM writes the intentionally unaligned interrupt base
`0x87`, requires the masked base/vector readbacks `0x80`/`0x81`, and dispatches
a selected X2 rising edge through vector `0x81`. Its exact `BDVIHRPACZ` bank
marker covers disabled-edge isolation, held-key non-retriggering, release and
repress, pending-status retention across masking, acknowledgement, and the
combined X2+Y1 matrix values `0x33` held/`0x30` released. A no-input control may
emit only the initial `B`; paired routed runs must have byte-identical traces,
frames, and raw/normalized input identities. This is translated-model evidence
for those controller/IRQ paths, not a measurement of physical interrupt
latency.

For a user-owned title, first use a private script and framebuffer output to
reach a readable text surface reproducibly. Then repeat that same reset-to-screen
route with unfiltered `mem`, `vram`, and the relevant `bg_cell`/`sprite_row`
events before running the provenance correlators below. Complete provenance
depends on history from reset release, so do not replace it with a late trace
start. Keep the ROM, input script, raw frames, traces, glyph tables, and other
title-derived artifacts private; this
repository needs only reusable code, open fixtures, and privacy-safe notes.

Build confirmation-grade reports for every completed display read and every
background cell promoted into a pixel-producing buffer:

```sh
./sim/verilator/run.sh \
  --rom /path/to/game.wsc \
  --frames 10 \
  --event-trace build/sim/text.csv \
  --trace-events mem,vram,bg_cell,sprite_row
python3 sim/verilator/correlate_provenance.py \
  build/sim/text.csv \
  --output build/sim/text-provenance.csv \
  --require-exact-fetches \
  --require-complete-coverage
python3 sim/verilator/correlate_bg_cells.py \
  build/sim/text.csv \
  --output build/sim/text-bg-cells.csv \
  --require-complete-coverage
python3 sim/verilator/correlate_sprite_rows.py \
  build/sim/text.csv \
  --output build/sim/text-sprite-rows.csv \
  --require-complete-coverage
python3 sim/verilator/report_glyphs.py \
  build/sim/text-bg-cells.csv \
  --csv build/sim/text-glyph-epochs.csv \
  --png build/sim/text-glyph-contact.png \
  --contact-mode unique-exact
```

Do not apply memory or display filters to the capture used for complete
provenance. Apply `correlate_provenance.py` output filters afterward so the
tool can reconstruct the full IRAM history. The atomic background correlator
also requires an exact, unfiltered capture. Every `bg_cell` must match a raw
Screen 1/2 fetch group; physical read-ahead that has not been promoted when the
capture ends is counted explicitly rather than mistaken for corruption.
`--require-exact-fetches` evaluates the complete capture before applying
report-output filters and rejects any value mismatch, mixed-port collision,
partial word, or unobserved byte. The older `--fail-on-mismatch` remains
available for exploratory reports where collision-marked uncertainty is
acceptable.

`report_glyphs.py` turns the atomic-cell CSV into a title-agnostic visual
index. Its complete CSV preserves every tile-use epoch, occurrence cycle,
normalized 8×8 bitmap fingerprint, map slot, writer origin, IRAM byte range,
and recoverable ROM source range. It decodes 2bpp and 4bpp planar/packed rows
and normalizes horizontal and vertical flips, but never guesses a character
identity. `--contact-mode unique-exact` keeps the CSV complete while drawing
one provenance-rich exact epoch for each distinct bitmap in the PNG; every
`E###` label points back to the original CSV epoch. Use `exact` or `all` when repeated
placements or incomplete/collision-marked candidates need visual inspection.
For both manifest versions, repeated normalized rows delimit occurrences
because neither the trace nor this report carries a renderer-aware frame event.
A v2 manifest separately supplies exact raw-frame publication cycles, but does
not add frame identity to the atomic-cell CSV or glyph report. The report keeps
exact renderer-event cycle spans instead of treating publication intervals as
pixel causality.

The 20-bit physical PC is `(CS << 4) + IP`, modulo 1 MiB. `--trace-pc` accepts
one or more comma-separated inclusive `START-END` ranges and treats them as a
union. It filters only `cpu` events; bank and VRAM events remain visible, which
makes a mixed trace useful even when instruction logging is tightly scoped.

`--trace-vram-address` accepts comma-separated 16-bit addresses or inclusive
ranges. `--trace-vram-role` accepts `screen1_map`, `screen1_tile`,
`screen2_map`, `screen2_tile`, `sprite_table`, `sprite_tile`, or `all`.
Multiple address ranges form a union; address and role filters combine with
AND. Both filters affect only `vram` events, so other events remain in a mixed
trace. They do not filter `bg_cell` or `sprite_row`; capture `mem`, `vram`, and
the relevant atomic event for complete provenance.

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

New traces use v5 unless `sprite_row` is requested, in which case the writer
uses the v6 extension below. Numbers are unsigned decimal values; inapplicable
CSV fields are empty and inapplicable JSONL fields are `null`.

`vram` is retained as concise CLI/event shorthand. WonderSwan has unified
internal RAM rather than a physically separate VRAM; these events are aligned
16-bit display reads expressed as 16-bit byte addresses.

| Field | Meaning |
| --- | --- |
| `cycle` | 36.864 MHz system cycle since reset was released |
| `event` | `cpu`, `bank`, `vram`, `mem`, `bg_cell`, or `sprite_row` |
| `physical_pc` | 20-bit CPU physical PC sampled at instruction completion |
| `cs`, `ip` | logical CPU location sampled at instruction completion |
| `address` | raw C0-C3 or accepted Bandai-2003 CE/CF/D0/D2/D4 I/O register for `bank`; aligned internal-RAM byte address for `vram`; raw 20-bit bus byte address for `mem` |
| `value` | bank-register byte, or raw completed 16-bit memory-bus value; use `byte_enable` only for writes and DMA transfers |
| `role` | display fetch role; empty/null for other events |
| `initiator` | `cpu`, `gdma`, or `sdma` for `mem` |
| `access` | completed `read` or `write` for `mem` |
| `byte_enable` | raw two-bit bus lane mask, 0-3; CPU reads use 0 because the CPU does not drive a read mask, and inherited SDMA reports 3 despite advancing one byte, so this field is not a general operand/sample-width encoding |
| `space` | `iram`, `cart_sram`, `cart_flash`, `cart_rom0`, `cart_rom1`, `cart_rom_linear`, `boot_rom`, `unmapped`, or `absent_sram` |
| `mapped_offset` | exact resolved byte offset within the backing space, including address bit 0; cartridge offsets include the active mask; null for unmapped/absent SRAM |
| `instruction_id` | monotonic CPU instruction-chain identity for exact CPU-owned `mem` and `bank` events; required to be nonzero on v5 `bank` |
| `origin_pc` | first byte of the owning instruction, including its first prefix, for exact CPU-owned `mem` and `bank` events |
| `origin_status` | always `exact` for `bank`; `exact`, `unattributed` for CPU traffic not bound to a decoded instruction (including observed prefetch/IRQ traffic), or `not_applicable` for DMA on `mem`; `unattributed` alone is not proof that a read was prefetch |
| `fetch_value` | completed 16-bit display-read word for `vram` |
| `fetch_collision` | 1 when the CPU/DMA write port addressed the same IRAM word on the display-read edge; otherwise 0 |
| `bg_layer` | 1 for Screen 1 or 2 for Screen 2 on `bg_cell` |
| `map_address`, `map_value` | completed screen-map word address and value promoted for the cell |
| `map_x`, `map_y` | 0-31 map coordinates decoded from `map_address`; these are map-space coordinates, not final screen pixels |
| `tile_bank_enabled`, `tile_index` | extended tile-bank mode and resulting 10-bit background index, or 9-bit sprite index decoded from its descriptor |
| `palette`, `hflip`, `vflip` | palette and flip attributes decoded from the map word; sprite palettes are reported as effective indices 8-15 |
| `bpp`, `packed` | 2/4-bit depth and planar/packed mode used for this row |
| `tile_row` | 0-7 row after vertical-flip selection |
| `tile_row_address`, `tile_row_bytes`, `tile_row_value` | exact contributing tile row: one 16-bit word for 2bpp or both words, low word first, for 4bpp |
| `map_collision`, `tile_row_collision` | mixed-port uncertainty on the promoted map word or contributing row |
| `sprite_table_address`, `sprite_table_value` | exact aligned source address and cached 32-bit descriptor accepted by `sprite_row` |
| `sprite_table_collision` | OR of the two descriptor-word mixed-port collision flags |
| `sprite_line_y`, `sprite_line_slot` | target scanline and 0-31 admitted line-buffer position |
| `sprite_table_generation` | zero-based completed OAM descriptor-DMA group latched with the descriptor; binds one exact raw table generation even when a later refresh has identical address/value data |
| `sprite_line_epoch` | zero-based line-loader occurrence; increments even for empty sprite lines so repeated 8-bit line numbers and overlapping descriptor DMA cannot blur slot ordering |

`cpu` is sampled on the instruction-complete pulse. `bank` reports one event
for each accepted CPU commit to common cartridge bank registers C0-C3. When
the canonical footer RTC/2003 selector byte is `01`, it also reports Bandai
2003 self-flash control CE and extended ports CF/D0-D5 while preserving the raw
port identity. Each v5 bank event
carries the exact owning instruction ID and first-byte physical PC; the
harness does not infer ownership. A held, identical
address/data/instruction tuple collapses to one transaction. A changed byte
tuple is committed even without an intervening low level, so a word `OUT`
produces ordered byte writes with one shared instruction origin; only its
accepted bank bytes are classified as `bank` events. Distinct identical commits
separated by a deassertion also remain visible. This byte-granular contract
follows the documented [C0-C3 mapper ports](https://ws.nesdev.org/wiki/Mapper),
[Bandai 2003 aliases](https://ws.nesdev.org/wiki/Bandai_2003), pinned Mesen's
[per-port 16-bit split](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsMemoryManager.cpp#L132-L190),
and pinned ares'
[extended I/O decode](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cartridge/io.cpp#L1-L141).
`vram` reports completed active graphics IRAM reads. Address/role
request metadata is delayed through the same
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
nearest instruction-complete event. CPU read events deliberately report
`byte_enable=0`: the functional CPU only drives byte enables for writes, so
forwarding that signal on a read would expose stale state from an earlier
write. GDMA's word transfers continue to report the raw bus mask. Do not infer
the width of a CPU read from this field.

CPU ROM-to-IRAM source classification is deliberately narrower than instruction
ownership. The correlator first requires an unattributed ROM read at the exact
instruction origin whose raw little-endian word contains the trace-observed
`F3 A4` (`REP MOVSB`) signature. It then accepts only an immediate ROM-read/
IRAM-byte-write pair with the same exact instruction ID and origin, the exact
mapped destination address, and the same low byte. Any intervening completed
memory row breaks the pair and retires the active chain. This is an observed
signature plus exact transfer; opcode signatures and successive transfers also
expire after 4,096 trace cycles to prevent stale instruction identities from
being reused. This evidence does not claim that `unattributed` by itself proves
prefetch, and it does not
generalize the evidence to `MOVSW` or other copy loops.

The regression instead generates a self-contained project-authored REP MOVSB
ROM and runs `verify_rep_movsb_probe.py`. Its versioned marker binds two
independent 2 KiB source/destination contracts and payload SHA-256 values. The
verifier requires the complete v5 manifest, trace-observed opcode origins,
strict alternating exact ROM reads and IRAM byte writes without interleaved
memory traffic, every address/offset/lane/value, distinct ordered instruction
IDs, intact destination windows, a final completion word, and the terminal PC.

The integrated top currently instantiates the DMA engine with its hardware
path enabled, so `sdma` events are runtime-reachable in the translated model.
The first generated WSC probe requires four one-shot reads at `0xf0100..0xf0103`,
including odd-byte alignment, and a 1,536 trace-clock interval: the documented
128 CPU clocks at the trace clock's 12:1 ratio. [WSdev revision 562 defines SDMA
transfers as bytes](https://ws.nesdev.org/w/index.php?title=DMA&oldid=562), while this inherited RTL drives the
shared DMA bus's raw `byte_enable=3` for both DMA engines. SDMA still advances
one address and consumes the low returned byte each step; do not infer its
sample width from the raw mask. The probe verifies translated-core cadence and
provenance, not the physical transfer's documented `117 mod 128` phase or
`6+N` stolen-cycle cost.

The second generated Color probe is self-checking: each exact C0 bank marker is
emitted only after its 80186 program verifies the corresponding visible
register or Channel 2 result. Two byte-identical captures contain exactly 21
selected `sdma` reads and the 12 exact-origin `PONSREATDHUZ` markers. Together
they cover masked pre-enable readback, one-shot terminal counters, zero-length
enable rejection, pause/resume, active low-byte source/length edits, edited
repeat-shadow reload, decrement, held-zero output with frozen counters, and
unhold completion. This is complete only for the selected `sdma` memory and
bank events; the manifest deliberately does not claim complete system-memory
history. A direct DMA-entity test separately forces queued-request cancellation
in IDLE and behind GDMA plus the one-completion boundary for an already-issued
read.

The hidden-state coverage follows pinned [Mesen2
serialization](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsDmaController.cpp#L196-L213)
of live/reload counters, control-derived state, frequency, and timer, plus
pinned ares [APU DMA
serialization](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/apu/serialization.cpp#L32-L44)
of programmed/live counters, control fields, and DMA clock. The FPGA's queued
request and shared-bus FSM checkpoint have no direct emulator counterpart.
`sim/rtl/run_dma_savestate_tb.sh` adds a separate direct save/load contract.
Legacy slot 17 remains unchanged. The existing unused zero slot 18 now carries
reload length `[19:0]`, reload source `[39:20]`, the 10-bit timer phase
`[49:40]`, queued request `[50]`, a fixed FSM code `[53:51]`, zero reserved
bits `[59:54]`, version `001` `[62:60]`, and valid bit `[63]`; the state-image
size does not change. The bench models state-bus capture and final-reset
restore, then checks the exact wire layout and round-trips a nonzero timer
phase, live/reload divergence through terminal repeat, a pending IDLE request,
and the sole legal in-flight checkpoint: a granted but not yet issued
`SDMA_READ`. Both enabled and post-grant-disabled pre-bus restores must produce
exactly one read and sample, advance the live counters once, and produce no
second transfer.

An all-zero extension is treated as a legacy image: slot 17's live counters
become the best-available reload values, while phase, request, and FSM restart
at zero/clear/IDLE. Reserved-bit or unknown-version headers select the same
fallback. A valid header with an impossible FSM/request combination retains
its versioned reload/timer payload but clears the transaction to IDLE. The
bench also proves that omitting the versioned extension loses a deliberately
divergent reload pair, so the added slot is not redundant. This is exact
translated-RTL continuation at the tested save-handshake boundaries, not a
claim for arbitrary mid-transaction snapshots or external save-state formats.

Pinned Mesen performs and traces a held memory read before substituting zero;
pinned ares skips the held read. The four held `0xf1070` rows therefore lock the
translated core's Mesen-aligned policy, not physical hardware activity. Rates
below 24 kHz, exact arbitration/phase/cost, slow-source extension, additional
source spaces and wrap, wider active-byte edits, Hyper Voice routing, and
hardware behavior remain outside this evidence.

The raw 20-bit address and resolved offset are both intentional. The mapper's
ROM0, ROM1, and linear windows can reach the same storage byte through different
bank registers. BIOS visibility takes precedence, and absent SRAM remains
distinct from the core's mono unmapped range. These rules match the [WSdev
memory map](https://ws.nesdev.org/wiki/Memory_map), [WSdev mapper
registers](https://ws.nesdev.org/wiki/Mapper), and pinned Mesen [address-to-ROM
conversion](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsMemoryManager.cpp#L440-L456).

`cart_flash` identifies Bandai 2003's byte-wide CE-selected mapping of ROM
through the `0x10000-0x1ffff` window. It has a resolved ROM offset and remains
distinct from ordinary `cart_sram`; the current observer label does not by
itself claim MBM29 command decoding or persistence.

The screen roles distinguish tile-map attribute reads from tile bitmap reads.
`sprite_table` identifies the 256 completed 16-bit reads made during line 144's
sprite-table transfer into the core's internal sprite buffer. Pinned Mesen2's
[`ProcessSpriteCopy`](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsPpu.cpp#L299-L310)
establishes one wrapping 16-bit word per cycle and explicitly latches count at
cycle 0, but reads base/first live during the line. Pinned ares instead takes
local count/base/first values on entry to its
[`oamSyncScanline`](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/sprite.cpp#L1-L22).
The RTL deliberately follows ares for that all-three cycle-0 boundary while
following Mesen for the complete 256-word physical copy; the byte offset wraps
inside the 512-byte table documented by WSdev
[Display/Sprites](https://ws.nesdev.org/w/index.php?title=Display/Sprites&oldid=507).
`sprite_tile` identifies sprite bitmap reads. A role describes an active fetch
source, not a guarantee that the word contributes a visible pixel. In
particular, all 256 table words are physical reads even when only a few cached
descriptors are selected by the captured count. V5 retains the completed
fetched word, but raw physical reads can still include pipeline or prefetch
work that does not contribute a pixel. Sprite-cache/transfer phase is absent
from the legacy GPU save payload and Pocket Memories remains unsupported;
reset therefore cancels an in-flight copy and a restored mid-line-144 raster
does not resume a partial table until the next genuine line-144 boundary.

`bg_cell` is the logical companion to those raw reads. It pulses when a
completed Screen 1 or Screen 2 fetch buffer is promoted into the buffer used by
the pixel shifter. It binds the map word to its decoded tile index, palette,
flips, format, and exact contributing tile row. The existing background engine
physically reads both aligned words around a row; in 2bpp only the word selected
by the row address can contribute, while in 4bpp both words contribute. The
event records that distinction instead of treating every raw tile read as
visible data. The 16-byte 2bpp and 32-byte 4bpp tile layouts, and therefore the
2-byte versus 4-byte row formulas, follow WSdev's
[tile-data specification](https://ws.nesdev.org/w/index.php?title=Display/Tile_Data&oldid=504).

This is a cell-consumption boundary, not a final-pixel assertion. A promoted
cell may still be outside a window, transparent, disabled, covered by the other
background or a sprite, or fetched for scroll prefill. The event also says
nothing by itself about glyph or character identity.

`sprite_row` provides the corresponding pre-pixel boundary for sprites. It
pulses on the edge where `sprites.vhd` accepts a vertically active descriptor
and completed tile row into one of its 32 next-line slots. The event carries
the exact cached descriptor source address/value/generation, line-load epoch,
target line, slot, decoded tile/palette/flips, mode, and contributing row. In
2bpp only the first physical
word contributes even though the current engine schedules a second read; in
4bpp both words contribute. Raw `sprite_table` and `sprite_tile` events retain
both physical reads.

Like `bg_cell`, `sprite_row` is not a final-pixel assertion. It precedes X
visibility, windowing, transparency, Screen 2 priority, palette RGB lookup,
and composition. Its attribute and scanline contract follows pinned ares
[OAM synchronization, scanline selection, and sprite decode](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/sprite.cpp#L1-L63),
Mednafen 1.32.1+dfsg-3's [sprite attribute/composition path](https://sources.debian.org/src/mednafen/1.32.1%2Bdfsg-3/src/wswan/gfx.cpp/#L784-L904)
and [2bpp/4bpp tile decode](https://sources.debian.org/src/mednafen/1.32.1%2Bdfsg-3/src/wswan/tcache.cpp/#L97-L168),
WSdev's pinned [sprite format](https://ws.nesdev.org/w/index.php?title=Display/Sprites&oldid=507),
and the pinned MIT ws-test-suite [extended-range fixture](https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/src/color/display/tile_screen_extended_range/main.c#L8-L134).
No directly applicable real-hardware report establishes this internal atomic
boundary, so acceptance is deliberately limited to translated RTL.
Mednafen is not used as evidence for the 32-sprite scanline limit; that limit
is locked separately by current RTL and the pinned open list-limit test.

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
changing the v4 prefix and requires exact instruction origin fields on bank
events. V6 preserves the complete v5 prefix and appends
`sprite_table_address`, `sprite_table_value`, `sprite_table_collision`,
`sprite_line_y`, `sprite_line_slot`, `sprite_table_generation`, and
`sprite_line_epoch`; the existing tile-row fields carry the decoded sprite row.
Output is conditional: a capture that does not request
`sprite_row` remains byte-for-byte v5, while one that requests it is v6.
Legacy v1-v4 bank rows retain empty provenance fields and remain accepted.
JSONL contains the matching conditional property set, although the standalone
verifier currently validates CSV only.

Every successful event capture also writes `FILE.manifest.json`. The manifest
records whether capture began at reset release, reached its requested frame
target, included unfiltered `mem` and `vram` history, included `bg_cell` or
`sprite_row` when requested, avoided save-state input, and can therefore use the defined zero
power-up state of IRAM. ROM and built-in Open IPL byte sizes and FNV-1a digests bind
the stimulus identity, while the trace byte length and digest bind the
certificate to the exact output file. These digests detect accidental or stale
artifact substitution; they are deterministic bindings, not cryptographic
authenticity claims. Starting a new capture at the same path invalidates the
old manifest before truncating the trace. The word-level correlator labels
coverage `complete_from_reset` only when the memory/display conditions hold.
The background atomic correlator additionally requires `events.bg_cell=true`
and `complete_bg_cell_history=true`. The sprite atomic correlator analogously
requires `events.sprite_row=true` and `complete_sprite_row_history=true`;
otherwise either tool refuses `--require-complete-coverage` and never treats an
absent write as zero.

By default the simulator preserves the exact manifest-v1 contract used by the
open probes. Add `--trace-frame-artifacts` to emit manifest v2 with an ordered
`frames` array. Each record binds zero-based `index`, `completion_cycle`, a
manifest-relative `file`, `size_bytes`, and lowercase FNV-1a digest. The bound
file is the raw 224×144 RGB888 `frame-N.rgb` artifact (96,768 bytes), not the
PNG that `run.sh` creates after the simulator exits. Verify the complete bundle
before using it as evidence:

```sh
python3 sim/verilator/verify_frame_manifest.py build/sim/game.csv
```

This command verifies the exact trace bytes, ordered frame identities, paths,
cycles, sizes, and contents recorded by manifest v2. For CSV event semantics,
also run `verify_trace.py` with the investigation's required events and ranges;
artifact integrity is not a substitute for schema/content assertions.
Manifest v2 requires the event trace and every listed frame to be distinct,
regular, non-symlink files. Raw frames are published through fresh temporary
files and renamed into place; their size and digest are captured at publication
and rechecked before the success manifest is atomically installed. This breaks
preexisting hardlink aliases and refuses later substitution instead of silently
adopting it.

`completion_cycle` is the 36.864 MHz trace-cycle label on which the harness
observes and copies the final visible framebuffer pixel at address 32,255. It
is a framebuffer-sweep publication boundary, not an exported hardware VBlank
or final-line strobe. WSdev documents the default 224×144 visible area within
[159 lines of 256 display clocks](https://ws.nesdev.org/w/index.php?title=Timing&oldid=645),
and the LCD final-line register is independently programmable
([Display I/O revision 582](https://ws.nesdev.org/w/index.php?title=Display/IO_Ports&oldid=582)).
Pinned ares likewise ends its hardware frame from `vcounter` and `vtotal`, not
from the final visible pixel
([PPU reference](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/ppu.cpp#L188-L228)).
Consequently the v2 timeline proves which raw artifact was published at each
cycle and detects stale or changed files; it does not by itself prove that an
arbitrary earlier fetch survived the renderer into that artifact. The atomic
background/sprite events remain the stronger renderer-aware provenance
boundaries. Trace CSV/JSONL remains byte-for-byte v5/v6 with or without v2.

`correlate_provenance.py` maintains IRAM per byte, respects partial and odd
writes, preserves exact CPU origins, pairs GDMA reads/writes only in protocol
order with matching value and byte enable, and applies the conservative
`REP MOVSB` rule above to CPU ROM-to-IRAM byte copies. For every display read
it compares the returned word with the independently reconstructed bytes and
reports the low/high writer and any mapped ROM source. A collision produces
`unspecified_collision`, while a non-collision disagreement produces
`mismatch`. Confirmation runs use `--require-exact-fetches`, which fails on
either condition and also rejects partial or unobserved data; output filters
cannot hide a global uncertainty. This proves graphics-data provenance; it
does not by itself prove that a tile index is a character code. Rasterized text can
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

`correlate_sprite_rows.py` independently pairs aligned raw OAM words into
descriptor snapshots, pairs each two-read sprite-tile group, and requires every
atomic promotion to reference its exact latched descriptor generation and the
exact raw row group. This avoids assigning a later identical-value OAM refresh
or its writer to an older cached descriptor. Writer and optional ROM-source provenance are
snapshotted on each raw-fetch edge. It treats the second 2bpp physical read as
noncontributing, while requiring both 4bpp words, and validates descriptor
decode, modular Y activity, vertical flip, row address/value, the one-cycle
raw-read-to-admission edge, strictly advancing line epochs, contiguous slots
within each epoch, and collision semantics. The explicit epoch remains correct
when a descriptor DMA group interleaves row admissions or a later frame reuses
the same 8-bit target line.
Its CSV proves that a descriptor and row reached a
line-buffer slot; it does not extend that claim through the compositor.

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

`make regression` runs that unit test plus explicit v1/v2/v3/v4/v5/v6 verifier
fixtures and focused byte-lane/background-cell/sprite-row correlator tests. Its
translated
open-ROM captures require all six display-role encodings, exact CPU memory
origins, `bg_cell`/`sprite_row` events, and nonzero atomic coverage from both
screen layers plus the sprite line buffer. The suite generates temporary bank,
WSC GDMA, and two WSC SDMA probes and runs a
checked-in native Shift-JIS fixture over `日本語かな漢`. The dedicated glyph
verifier binds the licensed Unicode/Shift-JIS manifest to 96 packed ROM bytes,
48 ordered GDMA read/write pairs, six exact CPU map writers, every promoted
glyph row and source offset, and the final 224×144 RGB pixels. It also requires
the reporter to produce 591 provenance-preserving epochs and a seven-image
unique-exact contact sheet whose six ROM-sourced entries have the expected
maps, fingerprints, IRAM spans, writer origins, and ROM offsets. This proves the
general Japanese-text provenance path while deliberately leaving any
commercial title's private codepoint mapping unclaimed. The
GDMA probe runtime-verifies linear-ROM and IRAM mapping with the ordered
completed chain `ROM 0x0100 -> IRAM 0x4000` and `ROM 0x0102 -> IRAM 0x4002`,
including known values and mapped offsets.
Two self-contained, build-generated, non-checked-in Color probes separately
select planar `0xc0` and packed `0xe0` 4bpp modes. Each transfers one exact
32-byte tile from linear ROM to IRAM `0x4020..0x403f`, then displays it at map
addresses `0x1a14/0x1a16/0x1a18/0x1a1a` with normal, H, V, and HV orientation.
The strict gate checks the complete manifest, 16 alternating GDMA word pairs, four
ROM-source lanes for every selected atomic row, reporter bitmap fingerprints,
and the stable second frame. It also requires the two different physical
encodings to produce identical normalized bitmaps and RGB output; the first
captured frame is retained for two-occurrence provenance but is not the final
pixel oracle because display setup overlaps its leading scanline.
The first SDMA probe runtime-verifies four successive byte addresses in linear
ROM, their even/odd returned values and offsets, `not_applicable` CPU origin,
the runtime initiator filter, and fastest-rate cadence. The second runs twice
and binds 21 selected reads to 12 self-checking success markers for the
live/shadow, pause/resume, repeat, decrement, zero-length, and held-zero subset;
the direct entity test covers pending cancellation and issued completion, and
the direct save/load test covers the exact versioned/legacy continuation
boundaries described above. The pinned open WSC fixture adds two byte-identical
15-frame captures with 346 exact SDMA rows, all 22 PASS markers, terminal PC
`0xff63a`, and exact final pixels. Its source-labeled SRAM phases are explicitly
43 segment-zero IRAM reads and zero cartridge-SRAM reads, so they establish no
SRAM or wait-state behavior; the fixture also does not pin physical transfer
phase or CPU-steal duration.
The pinned open mono interrupt fixture is run twice and binds all 13 PASS cells,
the exact terminal loop, complete background history, and its derived final
raster. It directly covers eight UART-send-ready and five vector/status
hardware assertions. The generated Color/input probe above covers the separate
key-edge and actual-dispatch paths; neither fixture establishes UART receive,
serialized transmit timing, cartridge IRQ, or exact interrupt latency.
Paired generated 2 MiB mapper
probes add complete-from-reset CPU coverage of all eight trace-space labels:
`iram`, `cart_sram`, `absent_sram`, `cart_rom0`, `cart_rom1`,
`cart_rom_linear`, `boot_rom`, and mono `unmapped`. The verifier binds the ROM
and generated Open IPL identities, requires the complete 37,035-event memory
history plus five exact bank writes in each trace, and checks resolved offsets,
masks, values, aliases, instruction IDs, and origin PCs. The eight Open IPL
carrier probes enter through the exact mono/Color reset vectors, bind contiguous
startup-tail execution for both bus widths and owner-area policies, and prove A0
lockout changes physical addresses `0xffff0..0xffffe` from mono offsets
`0xff0..0xffe` or Color offsets `0x1ff0..0x1ffe` to carrier-ROM offsets
`0x1fff0..0x1fffe`.
An additional generated pair declares SRAM types `0x01` and `0x02` and requires
byte-identical seven-row CPU traces: offsets `0x0000`, `0x2000`, and `0x7fff`
remain distinct, while address `0x18000` resolves to mirrored SRAM offset zero.
The focused companion contract locks the corresponding 32 KiB mapper,
save-state, Pocket block-count, and dynamic APF Save-slot authorities.
A separate black-box VHDL mapper test selects canonical footer RTC/2003 value `0x01` and
proves Bandai 2003's low-byte aliases `CF`, `D0`, `D2`, and `D4` share exact
readback state with `C0`-`C3` and produce the expected linear-ROM, SRAM, ROM0,
and ROM1 resolved offsets. It exhaustively writes all byte values to high-bank
ports `D1`, `D3`, and `D5`, requires the documented `000000bb` readback, checks
mapper gating/reset, and replays those bytes through the unchanged 256-port
save-state image. The same bench exhaustively verifies the four-bit `CC`/`CD`
GPO direction/data latches, including upper-bit masking, independence, reset,
mapper rejection, and register-image replay. No Pocket-side cartridge device
is attached to those latches. Mapper `0x00` and an unknown `0x03` cannot use
the extended ports. The test deliberately establishes no authority for ROM
above 16 MiB, physical GPO behavior, complete self-flash command behavior, or
KARNAK peripherals.

Those probes lock the translated RTL resolver and observer, not physical
hardware behavior. Current RTL returns zero for absent SRAM and `0x9090` for
mono unmapped reads; ares instead models absent SRAM as cartridge open bus,
while Mesen's fallback is marked as an open-bus TODO. Neither current-core
result is claimed as hardware-correct. The SRAM probe uses `ramtype=0x03`
(128 KiB) for its broad resolver coverage; the separate paired probe verifies
the corrected, research-consistent 32 KiB `0x01`/`0x02` interpretation.
Generated ROMs remain under `build/` and are never checked in.

Display provenance is now locked by four independent workload families. The
extended-range fixture requires 16,190/16,190 exact reads, the Shift-JIS
fixture 25,612/25,612, and each generated planar/packed 4bpp capture
26,170/26,170. Each inside/outside window capture adds 26,205/26,205 Screen 2
reads. Every run has zero value mismatch and collision and records the
expected exact CPU, initialized, and GDMA-ROM sources. All report zero
CPU-ROM-MOVSB display classifications; the separate generated REP probe proves
its two 2 KiB CPU copies directly instead of coupling CPU-copy correctness to
a display workload.
The atomic-cell gate validates 5,146 extended-range Screen 1 cells and 8,308
Shift-JIS cells. Of the latter, 96 records are the two complete promotions of
all 48 manifest-bound glyph rows. Each generated 4bpp capture adds 8,494
Screen 1 cells; 64 are the two complete promotions of the four diagnostic
placements, with both raw words and all four GDMA/ROM byte provenances exact.
Each window capture adds 8,463 provenance-complete Screen 2 cells and separately
locks the final Screen 2 and sprite-window pixels. Focused correlator fixtures
also cover simultaneous Screen 1/2 promotion.
The focused unit test locks 2bpp/4bpp
selection, simultaneous layers, collisions, superseded prefetches, and
writer-snapshot timing.
