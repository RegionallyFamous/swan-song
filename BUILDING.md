# Building and testing Swan Song

## What is currently verified

- GHDL 6.0.0 successfully analyzes and translates the VHDL console hierarchy.
- Verilator 5.050 successfully elaborates, compiles, and runs that translation.
- Project-authored generated REP MOVSB, Color sprite-priority, and dual
  window-boundary ROMs pass strict trace and deterministic 224×144 frame
  checks without carrying the 19 retired unlicensed MiSTer test assets.
- Wonderful's open WSC extended-range fixture renders all three PASS fields and
  proves that 2bpp Color mode fetches its map, bank-1 tiles, and sprite table
  above 16 KiB without aliasing; all 16,281 physical display reads match
  provenance (15,611 exact CPU-written words and 670 power-up reads).
  Its 32 atomic sprite-row events bind four cached descriptors to slots 0-3
  on lines 72-79 and distinguish 32 contributing 2bpp words from the engine's
  32 noncontributing second reads.
- Wonderful's open mono `80186_quirks.ws` fixture now renders all three PASS
  results for non-decimal-base AAM, non-decimal-base AAD, and D6/SALC. The
  strict gate binds the checked-in source, licenses, ROM/footer/font identities,
  terminal CPU loop, all 24 promoted PASS-tile rows, exact first/final frames,
  and byte-identical paired traces and framebuffers. Its stable final RGB
  SHA-256 is
  `871d7e2de2f915ceaae2a94fcf99b86825430f79588e43e640f9bfa8fed6dce0`.
  This upstream ROM checks result values; it does not test flags, AAM base-zero
  interrupt behavior, or instruction timing.
- Wonderful's open mono internal-EEPROM fixture renders all 23 hardware-path
  PASS results in two byte-identical captures, remains at terminal PC `0xff620`,
  and matches the exact target RGB SHA-256
  `830503147842b803d26b707675009e6b8e3b0faa1ee3ad1aef15c3e9e74e444d`.
  A focused controller bench covers separate data latches, EWDS/EWEN,
  WRAL/ERAL, protected/user words, invalid controls, DONE/READY, and a saved
  disabled-write latch. Its deterministic busy window is not a physical timing
  measurement, and the fixture does not exercise Color-hardware mono mode.
- A complementary build-generated mono probe covers those value-only test
  boundaries without checking in another binary. Its self-authored 128 KiB
  image has SHA-256
  `c0165695a4c236b61addd8cf1a27d1b9e5c0d47a67b1bc29f8e4af85d0b57ece`
  and needs no assembler, SDK, firmware, or carrier ROM. Twenty-four exact IRAM
  records prove AL-derived AAM parity/zero/sign (including nonzero quotient and
  zero remainder), all six AAD byte-ADD flags, AAM base-zero vector-0 entry with
  preserved AX and post-immediate return IP, and both SALC values with AH and
  the full before/after PUSHF words unchanged. Complete CPU-memory history
  proves no SALC data transaction. Prefetch credit affects observed completion deltas,
  so the probe does not relabel those deltas as a hardware clock measurement.
- The native open Shift-JIS fixture renders `日本語かな漢` from licensed Misaki
  rows and proves 48 exact GDMA word transfers (48 ROM reads paired with 48
  tile-RAM writes), six exact CPU map writers, two promotions of every glyph
  row, and every final RGB pixel. All 25,610 display reads match the
  reset-complete writer scoreboard.
- Paired build-generated, non-checked-in WSC probes exercise both documented
  Color 4bpp layouts: planar mode `0xc0` and packed mode `0xe0`. Each copies a
  distinct 32-byte ROM payload into tile 1, displays normal/H/V/HV placements,
  and proves 32
  ordered GDMA events, 64 selected atomic rows with four exact ROM-sourced
  bytes apiece, four provenance-bearing glyph epochs, and a pixel-exact final
  frame. Both encodings normalize to identical glyph fingerprints and RGB;
  their stable `frame-1.rgb` SHA-256 is
  `7f672cb770893d021bb6c684efccb9b118894f657e65dd4e8b966a2d90fefa5d`.
- A build-generated Color probe locks four targeted sprite-priority cases with
  8×8 panels: low sprite behind opaque Screen 2, the formerly broken
  earlier-low/later-high fallback, high sprite above Screen 2, and ordinary
  sprite-list order without Screen 2. Its strict two-frame gate proves the
  complete 256-word line-144 table transfer (including the 12 nonzero
  descriptor words), 96 sprite-tile reads, 48 packed 4bpp row promotions, 64
  exact GDMA words, 18 final CPU writes, zero display collisions, and a stable `frame-1.rgb` SHA-256 of
  `eb515b9c58a3fc7f386520937818d95b846a94cd43a86edef1daf54f3a4b5ef4`.
  A focused GHDL bench independently places the line-144 boundary at every one
  of the eight VRAM-arbiter phases under the four-clock fast-forward cadence,
  requires exactly one addressed word on cycles 0-255 and none on line 145,
  checks patterned low/high descriptor assembly across `FIRST=127` wrap, and
  proves late-line-143 count/base/first capture. The all-three latch follows
  pinned ares; pinned Mesen supplies the 256-cycle copy/count-latch contract and
  differs by reading base/first live mid-line. Reset cancels a partial transfer;
  because its hidden phase/cache is not in the legacy payload and Memories is
  unsupported, a restored mid-line-144 raster remains disarmed until next frame.
- The title-agnostic glyph reporter converts atomic-cell provenance into a
  complete deterministic epoch CSV plus a compact labeled PNG. On that fixture
  it retains 591 placement/provenance epochs while surfacing seven distinct
  exact bitmaps; six bind to the expected maps, writers, IRAM ranges, and ROM
  source ranges. It never assigns character identity from tile numbers alone.
- The structured-trace config parser and CSV/JSONL serializers have a standalone
  C++ unit test. The regression also validates CPU, display-RAM, and completed
  memory events from the
  translated model, including `CS:IP` conversion, inclusive PC/address filters,
  exact CPU memory origins, exact C0-C3 mapper-write instruction origins,
  resolved mapper offsets, completion-aligned display words/collision status,
  and the screen-map/tile and sprite-table/tile roles exercised by each
  translated workload. A dedicated clean-room REP MOVSB probe generates two
  independently initialized 2,048-byte chains from mapped ROM offsets
  `0x12000` and `0x15000` to disjoint IRAM windows `0x0800..0x0fff` and
  `0x2800..0x2fff`. Its verifier binds the exact generated ROM, versioned
  marker, complete v5 manifest, trace-observed `F3 A4` origins, uninterrupted
  alternating read/write chains, addresses, mapped offsets, lanes, all 4,096
  values, destination integrity, completion word, and terminal PC. The live
  run records 4,123 CPU and 8,250 memory events. Display-provenance correlation
  remains independently covered by the generated 4bpp, Shift-JIS, and
  extended-range workloads; `unattributed` alone is never treated as proven
  prefetch. The suite also generates build-only
  ROMs that verify all C0-C3 bank writes with their owning instruction IDs/PCs,
  including both accepted byte writes from one word `OUT`, and an exact GDMA
  ROM-to-IRAM chain.
- The translated trace runtime covers CPU, GDMA, and SDMA memory transactions.
  The first self-contained WSC probe streams four addressed bytes from linear
  ROM at the 24 kHz setting and requires the exact SDMA values, offsets,
  initiator, origin status, and 128-CPU-clock translated cadence. A second
  self-checking probe runs twice and requires byte-identical selected traces
  with 21 SDMA reads and the 12 exact-origin `PONSREATDHUZ` success markers for
  pre-enable readback, terminal and zero-length behavior, pause/resume, active
  low-byte edits, repeat, decrement, and held Channel-2 zero output. A direct
  DMA-entity test forces pending-request cancellation behind IDLE/GDMA and one
  already-issued completion. The inherited DMA bus reports raw
  `byte_enable=3` while SDMA still advances one byte per transfer, so the trace
  contract does not treat that mask as sample width. A pinned open Wonderful
  fixture adds paired 346-read captures, all 22 PASS markers, terminal PC
  `0xff63a`, and exact final pixels. Its two source-labeled SRAM phases are
  required to resolve to 43 segment-zero IRAM rows and zero cartridge-SRAM
  rows, exposing the toolchain limitation instead of claiming SRAM coverage.
  Direct save/load tests cover versioned and legacy continuation boundaries.
  Exact held reads record current translated policy; these tests do not
  establish physical `117 mod 128` phase, `6+N` stolen-cycle cost, slower-rate
  cadence, Hyper Voice, or hardware behavior.
- Paired generated 2 MiB mapper probes runtime-verify `boot_rom`,
  `cart_sram`/`absent_sram`, mono `unmapped`, `cart_rom0`, `cart_rom1`, and
  `cart_rom_linear` classification. Exact checks cover C0/C1 bank bits that
  survive their masks, C1 wrap through a declared 128 KiB SRAM, even-word and
  odd-byte writes, ROM aliases, resolved offsets, instruction origins, and the
  current core's readback values. Separate generated 4 KiB/8 KiB boot images
  prove mono and Color overlay offsets, execution from byte zero, a low-window
  marker read, A0 lockout, and the same top addresses becoming cartridge ROM.
  A second generated pair declares header values `0x01` and `0x02` and requires
  identical seven-event traces proving 32 KiB behavior: offsets `0x0000`,
  `0x2000`, and `0x7fff` remain distinct and `0x8000` mirrors zero. A focused
  contract also requires matching 32,768-byte mapper/save-state sizes, 64
  Pocket blocks, and the dynamic APF Save slot.
  These are translated-RTL contracts: absent-SRAM zero and mono-unmapped
  `0x9090` readback are regression-locked current-core results, not physical
  hardware/open-bus claims.
- V5 atomic Screen 1/2 background-cell serialization and conditional v6
  sprite-row serialization, map/descriptor and tile decode, 2bpp
  selected-word versus 4bpp two-word handling, collision semantics, and
  fetch-time writer snapshots pass focused C++/Python fixtures. Each sprite
  row also binds an exact latched OAM DMA generation, so an identical later
  refresh cannot steal its writer provenance, plus an explicit line-load epoch
  so overlapping DMA and repeated 8-bit line numbers cannot blur slot order. V6 preserves
  the exact v5 prefix and is emitted only when `sprite_row` is requested. The
  focused fixtures cover simultaneous Screen 1/2 behavior. Translated
  regression validates 5,177 extended-range Color cells and each generated
  window variant adds 8,494 Screen 2 cells. The Shift-JIS workload adds 8,308 Screen 1 cells,
  including 96 manifest-bound Japanese glyph-row promotions. The generated
  planar and packed workloads add 8,494 Screen 1 4bpp cells apiece, including
  64 exact diagnostic rows per encoding. All six translated runs
  account explicitly for superseded and end-of-capture prefetches.
- A pinned Wonderful-toolchain `initfini` ROM boots reproducibly, renders its
  constructor-pass checkmark, and produces identical traces and final frames in
  two runs. See `WONDERFUL_VALIDATION.md` for the exact source, toolchain, and
  hashes; the generated ROM is not checked in.
- The integrated APF startup path now locks the official lifecycle in RTL:
  Setup remains active through `008F`, delivered receipt of the one-time
  `0090` event, save metadata/table publication, and loader/initializer
  readiness. The sequencer issues target `0140` once, the command handler keeps
  Pocket-visible status in Setup until Pocket acknowledges it, and `0011` is
  required before Running. Early `0011` stays busy and holds the console in
  reset, while a new title invalidates any preceding title's `0140`
  acknowledgement. Focused APF boundary benches lock that progression, Reset
  Enter/Exit, slot update/all-complete behavior, and the three-word one-cycle
  RTC event.
- `0082` consumes the complete documented 48-bit expected length and the
  integrated data-slot guard returns the official per-request results: `0`
  ready, `1` not allowed ever, or `2` check later. Slot 0 accepts conventional
  power-of-two ROMs unchanged from 64 KiB through the implemented 16 MiB mapper
  limit, plus compact whole-64-KiB-bank images in that range. A compact image is
  accepted for execution only when its final 16-byte WonderSwan footer and
  checksum are valid; the loader fills the lower prefix with `0xff` and
  right-aligns the image in its next-power-of-two mapper aperture;
  slots 9 and 10 accept exactly 4 KiB and 8 KiB firmware respectively; slot 11
  accepts only absent, cartridge-canonical, or supported legacy EEPROM-save
  lengths once footer metadata is ready; fixed console-EEPROM slots 12 and 13
  accept exact 128-byte mono and 2,048-byte Color images in both load and
  shutdown-unload directions. Focused benches cover direction, unknown IDs,
  boundary sizes, retry-to-ready transitions, and malformed lengths.
- The host-notify bench also locks Pocket's unconditional `00B1` cartridge
  notification as an explicit no-op. `pocket_control_cdc_contract_test.py`
  mutation-locks independent memory/system reset and download copies, including
  async-assert/synchronous-release save-clear staging into the system domain.
  Another bench locks A0/A4 query fields, idle/busy/done/error precedence,
  save/load request hold-through-acknowledgement behavior, and fail-closed
  unsupported requests. The save-state envelope bench locks the source-derived
  `0x90300` payload, `SWAN`/version/length header, exact `0x90320` total, payload
  forwarding offsets, and 15 malformed/short/long/order adversaries. This is a
  staging-format foundation only; [`SAVESTATE_FORMAT.md`](SAVESTATE_FORMAT.md)
  explains why the inherited FIFOs cannot yet meet APF's complete-blob order.
  RTC command delivery now uses an acknowledged bundled-data CDC; its
  asynchronous-clock bench proves six coherent ordered epochs, one destination
  pulse per accepted event, and explicit busy rejection. Source contracts also
  lock per-title RTC state reset and one-shot trailer restoration.
  A separate 10 ms I2S waveform gate proves 12.288 MHz MCLK, 3.072 MHz SCLK,
  48 kHz signed stereo, coincident clock edges, left/right order, one-bit I2S
  delay, and zero spacer bits under two randomized initialization seeds. The
  I2S bench uses a behavioral CDC FIFO; physical FIFO and timing remain
  Quartus/Pocket gates.
- Pocket nonvolatile sizing is expressed in exact bytes: SRAM types `01/02`,
  `03`, `04`, and `05` use 32/128/256/512 KiB, while EEPROM types `10`, `20`,
  and `50` use 128/2,048/1,024 bytes. The 12-byte RTC trailer is now conditional
  on the cartridge footer bit, and `data.json` caps the dynamic slot at 524,300
  bytes. Header-derived type/RTC/size metadata crosses to `clk_74a` atomically;
  after `008F`, the core publishes slot index 3 / ID 11 with the exact payload
  plus optional trailer, and keeps that metadata alive across Reset Enter for
  shutdown flush. A focused RTL lifecycle bench proves that an absent external
  EEPROM is initialized to `0xffff` for exactly its selected word capacity, a
  loaded save is not cleared, and later Reset Enter/Exit cycles do not re-arm
  initialization.
  Offline legacy conversion and padded-EEPROM load compatibility are covered
  separately below. Full-wrapper unload and physical Pocket
  quit/reload/power-off flushing remain release gates; Sleep + Wake/Memories are
  not claimed or enabled.
- The APF build-ID generator no longer reads the live build clock or an RNG.
  A focused Tcl/Python contract proves that it preserves the 256×32 MIF shape,
  derives the three established words from a clean source commit and an
  explicit or commit-derived epoch, is timezone-independent, and fails closed
  on ambiguous source identity. Clean Linux/amd64 Quartus builds now produce
  valid RBFs, but two builds of the final release commit have not yet produced
  and compared byte-identical RBFs.
- The reverse-bit and deterministic APF package scripts are host-independent.
  Packaging materializes the core's required 411-byte `chip32.bin` offline,
  verifies both its assembly-source and image identities, and rejects missing,
  changed, or path-escaping core references. The image is the exact official
  assembler output for this fork's extended loader source.
- Quartus compilation, fitting, assembly, and four-corner TimeQuest passed in
  the pinned Quartus Lite 21.1.1 Linux/amd64 flow for protected-main commit
  `f0345ee4bae92cf137c600dfca876494cb17a5fe`. Workflow `29378537385` and a
  separate clean DigitalOcean build produced the identical RBF and build ID.
  The accepted historical candidate fits at 13,207/18,480 logic elements and
  289/308 RAM blocks, has minimum setup/hold/recovery/removal/pulse slack of
  `+0.426/+0.030/+3.679/+0.264/+0.753 ns`, zero critical warnings, and no
  unconstrained/check-timing findings. Its native IP summary has five `N/A`
  license rows, its Assembler inventory contains ordinary `ap_core.sof` and
  `ap_core.rbf`, and its bounded reports contain none of the pinned
  evaluation/time-limit warning or info IDs. It is historical hardware-QA
  candidate build evidence, not a public release or a legal conclusion; the
  newer source changes require a fresh accepted build and independent
  reproduction from the final public commit.
- No build has been confirmed on an Analogue Pocket in this fork.

## Simulation

Requirements:

- Docker (the default and CI path for the pinned GHDL translation image), or
  the explicit native-macOS GHDL wrapper described below
- Verilator 5.x
- a C++17 compiler
- Python 3
- Tcl (`tclsh`, for the reproducible build-ID contract)

Run the regression suite:

```sh
make regression
```

### Optional native GHDL on macOS

Docker remains the default local path and the immutable Linux CI contract. An
Apple-Silicon (`arm64`) Mac may instead run the same Docker-shaped RTL scripts
with the official `ghdl-llvm-6.0.0-macos15-aarch64` bundle from the
[GHDL v6.0.0 release](https://github.com/ghdl/ghdl/releases/tag/v6.0.0):

```sh
./scripts/with_native_macos_ghdl.sh \
  --bundle /absolute/path/to/ghdl-llvm-6.0.0-macos15-aarch64 \
  -- make regression
```

Use a narrower command while iterating:

```sh
./scripts/with_native_macos_ghdl.sh \
  --bundle /absolute/path/to/ghdl-llvm-6.0.0-macos15-aarch64 \
  -- sim/rtl/run_soc_control_tb.sh
```

The wrapper does not download or install anything. `--ghdl /absolute/bin/ghdl`,
`SWAN_GHDL_BUNDLE`, and `SWAN_GHDL` are explicit alternatives; only when none
is supplied does it look for `ghdl` on `PATH`. It accepts only the official
Apple-Silicon build whose first version line is
`GHDL 6.0.0 (6.0.0.r0.ge589c698c) [Dunoon edition]`, requires the LLVM backend,
and checks the bundle's `lib/ghdl`, `ghdl1-llvm`, `ghwdump`, and bundled
`libgcc_s.1.1.dylib`. This exact build check gives local runs a stable identity;
it is not a cryptographic archive attestation. Keep the extracted toolchain
outside the repository.

Some downloaded macOS bundles fail when their driver is launched in place,
and macOS removes `DYLD_*` variables while crossing its protected shell. The
wrapper therefore copies the minimal executable runtime—`ghdl`, `ghdl1-llvm`,
`ghwdump`, and its bundled `libgcc`—into a private temporary `bin` directory,
clears copied extended attributes, and removes the directory on success,
failure, or interruption. Docker environment/secret options are rejected.

This is deliberately not a general Docker replacement. Its temporary
`docker` command accepts only the exact `docker run --rm --platform
linux/amd64` subset used by the RTL tests, the project's tagged or
digest-pinned GHDL image identity, absolute non-overlapping volume mounts and
their mapped workdir, and either `ghdl` or a single generated test executable.
Unsupported options, images, commands, unmounted absolute paths, traversal,
and volume options fail closed. Absolute GHDL paths, `--option=/work/...`,
`-P/work/...`, and `-I/work/...` are mapped back to their mounted host paths.

The normal scripts, `make regression`, and GitHub workflow still invoke real
Docker unless this wrapper is selected explicitly. A native Mac run is useful
local evidence, but it does not replace the pinned Linux container result or
the separate Quartus fit, timing, and hardware gates. It is native execution,
not amd64 emulation, a container, or a security sandbox: the selected command
inherits the caller's host environment, filesystem permissions, and network
access, so Docker filesystem/network isolation is not reproduced. The
`.github/toolchain/verify.sh` identity check remains Docker-only and is never
routed through this wrapper.

### Pocket lifecycle and data-slot policy

This tree follows Analogue's current [core boot
process](https://www.analogue.co/developer/docs/core-boot-process) and
[host/target command](https://www.analogue.co/developer/docs/host-target-commands)
contracts. The relevant source-level order is:

```text
Setup -> 008F -> delivered 0090 + metadata/table/init ready
      -> target 0140 acknowledged by Pocket -> Idle -> 0011 -> Running
```

`0082` is decoded as one 48-bit byte count: the upper 16 bits in parameter 0
and lower 32 bits in parameter 1. Read and write requests independently return
`0` (ready), `1` (not allowed ever), or `2` (check later).

| ID | Purpose | Accepted host operation and size |
| --- | --- | --- |
| 0 | Cartridge | Write only; 64 KiB through 16 MiB in whole 64 KiB banks. Power-of-two images retain the legacy direct path; a compact image requires a valid final 16-byte WonderSwan footer/checksum and is `0xff`-prefilled/right-aligned into its next-power-of-two mapper aperture. APF persists the selected filename and performs a full core reload when it changes |
| 9 | Mono BIOS | Required write-only APF asset; exactly 4,096 bytes |
| 10 | Color BIOS | Required write-only APF asset; exactly 8,192 bytes |
| 11 | Save | Read becomes ready only after `reset_n=0`, synchronized execution has stopped, and a fixed 31-`clk_74a` drain guard has elapsed, with startup metadata/table/init still valid; write accepts absent (zero), canonical for the current cartridge, or legacy 2,060-byte RTC EEPROM type `10`/`50` |
| 12 | Mono console EEPROM | Optional fixed-name, core-specific nonvolatile machine state; exact 128-byte load and shutdown unload |
| 13 | Color console EEPROM | Optional fixed-name, core-specific nonvolatile machine state; exact 2,048-byte load and shutdown unload |

The slot-size response precedes receipt of the ROM bytes, so `0082` can reject
too-small, misaligned, or oversized compact files but cannot inspect their
footer. If post-load compact validation fails, the console remains in reset.
The compact loader accepts the first raw word promptly, then, while its prefix
remains incomplete, schedules at least one `0xffff` prefix word after every
accepted raw 16-bit word and before the next. For any accepted compact size
`S` in aperture `P`, `P/2 < S < P`, so `P-S < S`: there are strictly fewer
prefix words than raw words and fill is complete before EOF even for a
continuously held raw stream. This avoids stalling the first word long enough
to overflow `data_loader`'s small non-backpressured CDC FIFO. The focused RTL
bench proves the continuous-stream invariant; the documented bridge cadence
(about one 32-bit transfer per 75 `clk_74a` cycles) leaves substantial memory-
clock service margin, but Quartus and physical Pocket remain required gates.
Chip32 polls the synchronized PMP status at `0x14`: ready continues startup,
failure prints **ROM footer/checksum rejected** and exits with an error, and a
stuck-pending implementation is bounded to 1,048,576 polls before printing
**ROM validation timed out**. That counter is an instruction guard, not a
wall-clock promise: Analogue publishes neither the Chip32 execution rate nor
its crash-cycle threshold, and firmware 1.1 beta 5 explicitly added a
[Chip32 cycle limit during crash](https://www.analogue.co/developer/docs/changelog/1-1-beta-5).
Pocket fault-injection/calibration must therefore prove that the core's visible
timeout wins on the target firmware before this negative path is considered
hardware-accepted. Re-selecting a corrected cartridge performs a full core
reload and is the recovery path; RTL regression proves rejected-compact to
valid-compact recovery. The existing power-of-two route deliberately keeps its
previous acceptance behavior and reports ready immediately. The generated 896
KiB regression image contains only repository-authored diagnostic content; it
maps at `0x020000..0x0fffff` in a 1 MiB aperture and proves the `0xff` prefix,
footer/reset-vector placement, checksum, and mapper mask without copying
commercial or third-party ROM content.

The source-mutation contract locks both the two-bit memory-to-`clk_74a`
terminal synchronizer and the exact PMP `0x14` read mux. A compiled full-wrapper
behavioral observation and physical Pocket log are still open; source-string
coverage alone is not presented as CDC or hardware proof.

Slots 9 and 10 use `required: true` and `size_exact` in `data.json`, matching
the current Chip32 program, which queries and loads both BIOS files on every
launch. This lets APF surface missing or malformed firmware at its normal file
boundary instead of advertising an optional asset that the launcher later
rejects. They are read-only assets with APF's persist-browsed-filename bit, so
a one-time browser choice is reused until **Reset all to defaults**. The exact-size
RTL guard remains a second, independent check.

Slot 0 uses APF parameter `0x309`: user-browsable, read-only, full-core reload,
and persisted browsed filename. This makes a normal launch reuse the last title
while **Core Settings > Cartridge** remains the explicit game switcher. The
full-reload path performs normal shutdown first, allowing slot 11 to flush the
old title before Chip32 derives and loads the new title's save. `core.json`
declares Pocket firmware 2.3 as the minimum because its **Reset all to
defaults** behavior correctly clears this browser history.

Before cartridge metadata is available, a plausible slot-11 write returns `2`
instead of guessing. Once metadata is ready, type-inconsistent, short,
oversized, and legacy type-`01` lengths return `1`. Canonical save sizes are:

| Footer type | Payload | With RTC trailer |
| --- | ---: | ---: |
| none | 0 | 12 bytes only when the footer declares RTC |
| SRAM `01`/`02` | 32 KiB | 32,780 bytes |
| SRAM `03` | 128 KiB | 131,084 bytes |
| SRAM `04` | 256 KiB | 262,156 bytes |
| SRAM `05` | 512 KiB | 524,300 bytes |
| EEPROM `10` | 128 bytes | 140 bytes |
| EEPROM `20` | 2,048 bytes | 2,060 bytes |
| EEPROM `50` | 1,024 bytes | 1,036 bytes |

The runtime data-slot table is updated only after the metadata has crossed
clock domains coherently and all boot-time slot access is complete. Analogue
reads that table during nonvolatile flush, as specified by
[`data.json`](https://www.analogue.co/developer/docs/core-definition-files/data-json).
The declarations and physical bridge boundary are governed by
[`core.json`](https://www.analogue.co/developer/docs/core-definition-files/core-json)
and [bus communication](https://www.analogue.co/developer/docs/bus-communication).

ROM support is intentionally narrower than the most permissive hardware
interpretation. [WSdev's ROM-header table](https://ws.nesdev.org/wiki/ROM_header)
documents known values through 16 MiB, while its [Bandai 2003
documentation](https://ws.nesdev.org/wiki/Bandai_2003) defines 10-bit D0/D2/D4
bank registers and therefore a theoretical 64 MiB ROM address. Swan Song now
models their D1/D3/D5 high-byte read/write/reset/save semantics, including the
documented zero upper bits, but still implements only a 24-bit ROM address and
therefore rejects anything above 16 MiB. Widening the resolver alone would be
unsafe: ROM above 16 MiB currently overlaps the Pocket SDRAM ranges reserved
for cartridge SRAM and save-state staging. Pocket exposes one [64 MiB
SDRAM](https://www.analogue.co/developer/docs/external-hardware), so a full
64 MiB ROM cannot coexist there with those writable regions; the loader, APF
slot policy, memory layout, trace ABI, simulator, and persistence paths must
move together around an explicit capacity policy.
The [Wonderful WonderSwan target
documentation](https://wonderful.asie.pl/docs/target/wswan/) is the modern
toolchain reference used by the open generated-ROM validation; it does not
raise the core's implemented limit.

### Supported Pocket launch boundary

The packaged product is an openFPGA SD-card asset launcher for `.ws` and `.wsc`
images with both legally obtained BIOS files. It uses APF for data slots,
video, audio, input, saves, settings, and Dock transport. It does not enable
Pocket's physical cartridge adapter or link port, does not participate in the
first-party physical-cartridge/Library launch flow, and does not bundle BIOS or
commercial game data. [POCKET_LAUNCHER_LIBRARY.md](POCKET_LAUNCHER_LIBRARY.md)
records the current firmware, Recent, platform-art, Library-image, cartridge
adapter, and unsupported-firmware boundaries behind that statement.

Only Auto, WonderSwan, and WonderSwan Color are exposed as system types.
PocketChallenge v2 is outside the supported boundary: this core does not
implement the machine's pinstrap boot, distinct keypad matrix, absent internal
EEPROM, or native `.pc2` asset path. Separately, the display-presentation menu
does not replace the console's live orientation signal, which remains the
authority for the emulated input matrix.

### Migrating legacy type-01 Pocket saves

Pocket packages made from the inherited 1.0.1 core treated WonderSwan header
type `0x01` as 8 KiB. The corrected core uses the documented 32 KiB layout, so
an old 8,204-byte file must not be loaded directly. Convert it to a new path:

```sh
./scripts/migrate_type01_save.py \
  /path/to/type01-game.ws \
  /path/to/legacy-8204-byte.sav \
  /path/to/new-32780-byte.sav
```

The tool requires a checksummed ROM whose footer declares exactly type `0x01`
and an exactly 8,204-byte input. It preserves the first 8,192 SRAM bytes,
zero-fills the newly exposed 24 KiB, moves the opaque 12-byte RTC trailer to
the end of the 32 KiB SRAM region, prints input/output hashes, and refuses to
overwrite or alias either input. It never changes the original save. If the
output filesystem cannot atomically create without replacement, create the
new file on a local filesystem and then copy it to the SD card. Data already
lost through the old 8 KiB address alias cannot be recovered.

### Migrating padded type-10/type-50 Pocket saves

Inherited Pocket builds allocated 2,048 EEPROM bytes before the RTC trailer
for every external-EEPROM cartridge. Type `0x10` actually has 128 bytes and
type `0x50` has 1,024 bytes, so their old RTC-bearing saves are 2,060 bytes
instead of the canonical 140 and 1,036 bytes. Convert an old file to a new
path before copying it back to the Pocket SD card:

```sh
./scripts/migrate_legacy_eeprom_save.py \
  /path/to/type10-or-type50-game.ws \
  /path/to/legacy-2060-byte.sav \
  /path/to/new-exact-size.sav
```

The tool requires a checksummed ROM whose footer declares type `0x10` or
`0x50` and an exactly 2,060-byte input. It preserves the exact EEPROM payload,
drops only the inherited padding between that payload and byte 2,048, moves
the opaque 12-byte RTC trailer directly after the payload, prints hashes for
each region, and refuses to overwrite or alias either input. The original is
never changed. The RTL loader also acknowledges old padding and recognizes a
legacy RTC marker at byte 2,048 so an unmigrated file cannot stall startup;
new save flushes expose only the canonical exact-size layout.

### Publishing the reviewed GitHub Wiki

`docs/wiki` is the reviewable Wiki source. Publication uses an explicitly
supplied, fresh local clone; the project never discovers, clones, fetches, or
changes a Wiki implicitly. After the source documentation and all of its
`blob/main` targets are merged, create a normal clone with your already
configured Git or GitHub CLI credentials:

```sh
git clone https://github.com/RegionallyFamous/swan-song.wiki.git \
  /absolute/path/to/swan-song.wiki
python3 scripts/wiki_sync.py \
  --wiki-clone /absolute/path/to/swan-song.wiki
```

The default is offline and read-only. It runs `wiki_publication_check`, proves
the clone is clean, root-level, on a branch tracking the expected `origin`, and
contains only tracked regular Markdown pages, then prints every add, change,
and delete. It rejects wrong remotes, known branch divergence, unexpected
files, symlinks, nested paths, invalid UTF-8, and any source change after the
plan. Review that complete plan before publishing:

```sh
python3 scripts/wiki_sync.py \
  --wiki-clone /absolute/path/to/swan-song.wiki \
  --apply \
  --confirm-publish RegionallyFamous/swan-song.wiki
```

Only that exact `--apply` plus confirmation combination copies the planned
pages, deletes planned retired pages, stages the exact path/status set,
commits, and pushes the clone's current branch. `.git` is never copied or
removed. Git credential and terminal prompts are disabled so the command fails
closed in automation. If authentication fails after the local commit, inspect
that clean commit and push it explicitly after fixing credentials; do not
discard or rerun over an ahead clone. `--json` provides a machine-readable
dry-run or apply result. Neither mode fetches, creates a clone, tags the source
repository, or creates a release.

### Exact CI toolchain

The GitHub regression workflow runs the same `make regression` entry point but
does not install a moving Ubuntu package. It pins:

- [`actions/checkout` v7.0.0](https://github.com/actions/checkout/commit/9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0)
  by full commit SHA `9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0`;
- the [official Verilator executable container](https://verilator.org/guide/latest/install.html#verilator-executable-docker-container)
  at version 5.050 and multi-architecture image index
  `sha256:c531ae1e5da8e7293a2bd6793060c2bf484dac358746e69bcc3e689ec265b299`,
  including GCC 13.3.0 for both Verilator's model build and the standalone C++
  trace tests; and
- the [GHDL-maintained](https://github.com/ghdl/docker) 6.0.0 LLVM/Ubuntu 24.04
  image at
  `sha256:8b3ec37c3873b2eee9387759e66c50830c15ae5b7b533badaa97ce007a0f8022`.

`.github/toolchain/verify.sh` pulls only those immutable image identities and
checks the exact Verilator version, source revision, compiler version, and GHDL
version before the regression starts. The workflow passes the GHDL digest
through the existing `GHDL_IMAGE` override and puts the pinned Verilator wrapper
on `PATH`; local simulation continues to use the host Verilator unless that
wrapper is selected explicitly.

```sh
.github/toolchain/verify.sh
```

On macOS this command verifies the multi-architecture Verilator image and the
amd64 GHDL image, but a simulator compiled inside the Linux container cannot run
as a native macOS executable. The complete container-backed regression is
therefore a Linux CI contract. GitHub's `ubuntu-24.04` host still supplies Bash,
Make, Docker, Python 3, Tcl, and Git; their patch releases are platform-managed rather
than independently image-pinned, while the regression's exact output hashes
remain the behavioral drift gate. No successful remote run is claimed for the
current working tree until it is pushed; the last protected-main regression
(`29377588945`) and Quartus run (`29378537385`) are explicitly bound to
historical commit `f0345ee4`, not the newer local changes.

Generate a clean-room window-boundary ROM, run two frames, and emit PNGs:

```sh
python3 sim/verilator/generate_window_boundary_probe.py \
  --output-dir build/sim/window-boundary/roms
for variant in inside outside; do
  ./sim/verilator/run.sh \
    --rom "build/sim/window-boundary/roms/wsc_window_${variant}_probe.wsc" \
    --frames 2 \
    --out "build/sim/window-boundary/${variant}-frames"
  python3 sim/verilator/verify_window_boundary_probe.py \
    --variant "$variant" \
    --rom "build/sim/window-boundary/roms/wsc_window_${variant}_probe.wsc" \
    --frame "build/sim/window-boundary/${variant}-frames/frame-1.rgb"
done
```

Add `--trace build/sim/window-boundary.vcd` for a VCD or
`--bios /path/to/color.rom`
to test with a legally obtained 8 KiB Color firmware image. Without `--bios`, the harness
programs a nine-byte open bootstrap suitable for these generated ROMs. The
harness never searches for or downloads firmware.

### Structured event traces

The VCD option captures the whole translated design. For a smaller,
machine-readable stream, select one or more of the `cpu`, `bank`, `vram`, `mem`,
`bg_cell`, and `sprite_row` event classes. `translate_vhdl.sh` sets the compile-time `SwanTop.is_simu`
generic for this simulator build; the production default leaves it disabled.

```sh
./sim/verilator/run.sh \
  --rom build/sim/window-boundary/roms/wsc_window_inside_probe.wsc \
  --frames 2 \
  --event-trace build/sim/window-boundary.csv \
  --trace-events cpu,mem,vram
```

CPU records can be limited to a union of comma-separated inclusive 20-bit
physical-PC ranges. These ranges apply only to CPU events, so bank and VRAM
activity remains available in a mixed trace:

```sh
./sim/verilator/run.sh \
  --rom /path/to/legally-obtained-title.wsc \
  --frames 10 \
  --event-trace build/sim/text-renderer.jsonl \
  --trace-events cpu,bank,vram,mem,bg_cell,sprite_row \
  --trace-pc 0x80000-0x8ffff,0xf0000-0xfffff \
  --trace-vram-role screen1_tile \
  --trace-vram-address 0x2000-0x5fff
```

Use `--trace-format csv|jsonl` to override suffix-based format selection. For a
repeatable investigation, copy `sim/verilator/trace.example.conf`, then pass
`--trace-config FILE`. Later command-line options override config-file values.
The config accepts the CPU/display filters plus memory initiator, access,
address, mapped-space/offset, and instruction-origin filters. Full field
semantics and filtering behavior are in
`sim/verilator/TRACE.md`.

Run the parser/serializer unit test independently of GHDL and Verilator:

```sh
mkdir -p build
c++ -std=c++17 -Wall -Wextra -Werror \
  sim/verilator/trace_logger_test.cpp \
  -o build/trace_logger_test
./build/trace_logger_test
```

This unit test proves config parsing, filtering primitives, and serialization.
`make regression` separately runs `verify_trace.py` against an end-to-end ROM
capture to check all six CSV schema versions, event-specific fields, monotonic cycles,
`CS:IP` to physical-PC conversion, and requested PC/address/role containment.
The same regression generates (but does not check in) minimal open bank-write,
WSC GDMA, two WSC SDMA, dual-format 4bpp, paired mapper-memory, and mono/Color
boot-overlay probes. The GDMA
probe requires two known ROM words to appear in the ordered completed
read/write events at their resolved ROM and IRAM offsets. The first SDMA probe
requires four byte-addressed linear-ROM reads, including odd addresses, at the
fastest documented cadence through the runtime `sdma` filter. The second SDMA
probe binds every selected read and exact-origin success marker across two
byte-identical captures; the direct GHDL test covers request-cancellation edges
that software cannot schedule reliably. The mapper probes
require complete unfiltered memory history, exact values and resolved offsets,
issued write lane masks plus the CPU-read zero convention, and exact
instruction origins for probe-owned accesses across the paired trace-space
coverage.
The boot probes bind both input images and prove the overlay-to-cartridge
transition at identical physical addresses.

The checked-in
`testroms/ws-test-suite/80186_quirks/80186_quirks.ws` regression runs twice
with CPU and atomic-background tracing. Its dedicated verifier binds the
pinned MIT/zlib source inputs and exact ROM, requires the final 128 CPU events
to remain in the fixture's idle loop, rejects any FAIL tile at the three result
positions, reconstructs all eight rows of every PASS marker from the embedded
font, and compares both traces and both frame pairs byte for byte. Focused
mutation tests reject changed source, footer, checksum, ROM, terminal state,
result tile, framebuffer, manifest, and paired-run identity.

The generated CPU-quirks probe separately binds its exact authored program,
marker, footer, checksum, ROM and boot identities, complete v5 CPU/memory
manifest, every result write and owning PC, adjacent SALC completions, and the
halt boundary. Its mutation suite flips each AAM/AAD/INT0/SALC contract,
instruction origin, ROM, manifest, and SALC memory behavior; even an
unattributed IRAM read inserted into a SALC interval is rejected, while normal
ROM prefetches must match the generated image exactly.

The simulator also accepts a strict `--input-script FILE` schedule keyed to
36.864 MHz system cycles from reset release. The integrated regression uses an
authored, build-generated keypad probe to prove that physical X2 crosses the
real B5 matrix, that no marker is reachable without input, and that two runs
produce identical trace/frame bytes. Scripted trace manifests bind raw and
normalized schedule identities; `verify_input_script_manifest.py` rejects
changed scripts, traces, or completion fields. The exact grammar and a private
user-owned-title workflow are documented in `sim/verilator/TRACE.md` and
`sim/verilator/input.example.input`.
The 4bpp probes are repository-authored 80186 code and data with no assembler,
SDK, carrier ROM, or checked-in binary. Their strict verifier binds the
generated ROM hashes and footer checksums, complete v5 manifests, all 16 GDMA
read/write pairs, all four provenance lanes on 64 selected atomic rows, the
normal and flipped reporter epochs, and the stable 224×144 RGB output. It also
requires planar and packed captures to render byte-identically.
The Color sprite-priority probe is likewise repository-authored and generated
only under `build/`. Its verifier binds the ROM, complete v5 trace, exact OAM
snapshots, packed tile reads, ROM-to-IRAM GDMA chain, CPU descriptor/map/palette
writes, four complete color panels, black borders, and the stable frame. The
mutation suite explicitly rejects the previous opaque-Screen-2 result.
The separate project-authored window-boundary pair locks inclusive Screen 2
left/top/right/bottom comparisons and each sprite's bit-12 inside/outside
selection. Both generated ROMs bind 24 named boundary samples and a complete
stable frame; their mutation suite rejects all 48 sample inversions plus ROM
and nonsampled-frame drift. Each translated capture also requires all six VRAM
roles, 26,296 exact display reads with zero mismatch/collision, and 8,494
provenance-complete Screen 2 cells.
The generated REP MOVSB verifier independently locks two 2 KiB CPU copies to
the exact authored source and destination windows. It requires trace-observed
`F3 A4` origins, exact immediate ROM-read/IRAM-write pairs, distinct ordered
instruction IDs, no extra copy chains, both intact final windows, and a
completion write after both transfers.
The v5 path additionally runs `correlate_bg_cells.py`: it independently groups
Screen 1/2 map and tile reads, validates each promoted atomic background cell,
and preserves the writers observed on the raw-fetch edge rather than consulting
IRAM at the later promotion edge. Focused fixtures exercise both layers;
translated workloads exercise Screen 1, while both window variants exercise
Screen 2 and separately prove the final composed pixels. This proves the promoted map and contributing tile row, not that any
specific pixel survived windows, transparency, priority, sprites, or clipping.
The Shift-JIS workload then runs `report_glyphs.py` over the atomic CSV and
requires its provenance ledger and four-column `unique-exact` contact sheet to
recover the six manifest-bound glyph candidates. The reporter's focused tests
cover 2bpp/4bpp planar and packed decoding, both flips, repeated and rewritten
epochs, incomplete/mixed/collision states, and byte-identical CSV/PNG output.
The capture manifest is bound to the trace, ROM, and boot image by sizes and
FNV-1a digests; dedicated fixtures separately lock their generated inputs with
SHA-256. Regression also proves a failed same-path rerun removes the preceding
success certificate.

For resumable exploratory smoke tests across a private, legally held ROM
collection, see [`PRIVATE_CORPUS_TESTING.md`](PRIVATE_CORPUS_TESTING.md). That
runner keeps ROMs, BIOSes, frames, logs, and paths outside the repository and
emits only secret-keyed, sanitized results. It is separate from the cloud
Quartus Lab below, which never receives ROM or BIOS data, and it does not
replace physical Pocket/Dock acceptance.

Generated VHDL-to-Verilog files, binaries, traces, raw RGB frames, and PNGs live
under `build/` and are ignored by Git.

## Quartus

For a launchable native x86_64 cloud worker that Codex can control from an
authenticated Mac terminal, see [`SWAN_SONG_LAB.md`](SWAN_SONG_LAB.md). Its
DigitalOcean control surface is a dry run by default, prepares the exact local
Quartus Docker image before registering a one-job GitHub JIT runner, and
deletes the Droplet, attached volume, firewall, tag, and runner explicitly.
It never handles ROM or BIOS data.

The checked-in project records Quartus 18.1.1 as its original version and
21.1.1 Lite as its last-saved version; `ap_core.qpf` still declares 18.1. The
build helper expects 21.1.1 and has completed engineering builds in the pinned
Linux/amd64 container on the trusted x86_64 lab. Those probes establish that
the tool/device flow can build this project; they do not establish the final
commit, repeatable RBF output, or hardware acceptance. The project targets
Cyclone V device `5CEBA4F23C8`; Quartus Lite is supported on Linux and Windows,
not natively on macOS. On Apple Silicon, the fail-closed Docker workflow in
[`QUARTUS_MAC_DOCKER.md`](QUARTUS_MAC_DOCKER.md) verifies the official archive
and runs the Linux/amd64 tool under emulation. Docker documents that emulation
as best effort, so an emulated invocation must produce and pass its own complete
fit/evidence set rather than borrowing the x86_64 lab result.

On a supported host with `quartus_sh` on `PATH`:

```sh
make quartus
```

This runs:

```sh
cd src/fpga
quartus_sh --flow compile ap_core
```

The expected raw bitstream is `src/fpga/output_files/ap_core.rbf`. Do not call
the build timing-clean until the fitter and TimeQuest reports show no failing
paths.

### Reproducible build identity

Quartus runs `src/fpga/apf/build_id_gen.tcl` before each flow. Its MIF values are
now reproducible source metadata rather than build-host state:

- `0E0` and `0E1` are the source epoch formatted in UTC as `YYYYMMDD` and
  `00HHMMSS`.
- `0E2` is the first 32 bits of the full source commit ID.
- In a Git checkout, the source ID defaults to `HEAD`, the epoch defaults to
  that commit's timestamp, and tracked source must be clean. The generated
  `src/fpga/apf/build_id.mif` is the sole excluded tracked path because the
  pre-flow script necessarily rewrites it.
- `SOURCE_DATE_EPOCH` may override the commit timestamp using the standard
  [reproducible-build timestamp contract](https://reproducible-builds.org/specs/source-date-epoch/).
  `SWANSONG_SOURCE_COMMIT` may assert the expected full commit, but must match
  `HEAD`.
- Outside a Git checkout, both `SOURCE_DATE_EPOCH` and
  `SWANSONG_SOURCE_COMMIT` are mandatory. Missing or malformed identity fails
  the flow instead of falling back to the wall clock or a random value.

Run the standalone generator contract with a system Tcl interpreter:

```sh
python3 src/fpga/apf/build_id_gen_test.py
```

This proves deterministic MIF generation and source/epoch validation without
Quartus. It is not proof that place-and-route is reproducible. Phase 0 still
requires two clean Quartus 21.1.1 builds of the exact same final commit and
epoch with identical RBF hashes, complete accepted fitter/TimeQuest evidence,
and the separately authorized physical Pocket/Dock check.

## Reverse and package

APF reverses the bit order within every byte of the Quartus RBF. Package a
successful compile with:

```sh
make package
```

or explicitly:

```sh
./scripts/package_core.py \
  --rbf src/fpga/output_files/ap_core.rbf \
  --output build/SwanSong.zip
```

To produce only the reversed bitstream (without a ZIP), run:

```sh
./scripts/reverse_rbf.py \
  src/fpga/output_files/ap_core.rbf \
  build/wonderswan.rev
```

The core definition also delegates loading to a required Chip32 program. To
materialize and verify that program independently of Quartus, run:

```sh
make chip32
```

This produces `build/chip32.bin` from the checked-in canonical hexadecimal
image only after `src/support/chip32.asm` and the decoded 411-byte image match
their pinned SHA-256 identities. It requires no network access or host
assembler. The encoded image is the exact output of the official
[open-fpga/bass-chip32 v1.0.0](https://github.com/open-fpga/bass-chip32/releases/tag/v1.0.0)
for the checked-in assembly. It is intentionally larger than the loader in
[agg23's WonderSwan 1.0.1 package](https://github.com/agg23/openfpga-wonderswan/releases/tag/1.0.1)
because it adds fixed console-EEPROM loads and visible compact-ROM validation;
the current identity is pinned in `scripts/build_chip32.py`.
The package command performs this validation again and writes the result under
the exact filename declared by `core.json`; it never downloads a tool or
artifact.

The script copies `dist/`, writes the reversed stream as the filename declared
by `core.json` (`wonderswan.rev`), adds its declared `chip32.bin`, rejects
every path outside the release allowlist (including `.ws`, `.wsc`, `.rom`, and
`.sav`), and writes entries in sorted order with fixed timestamps. Before
staging, `package_validator.py` checks all seven APF core JSON definitions and
the platform JSON with an exact, fail-closed Swan Song release profile: required
members, unknown members, APF limits, integer ranges, unique IDs, safe
filenames, documented key/display values, cross-file platform/core identity,
the official [32-line printable-ASCII `info.txt`
limit](https://www.analogue.co/developer/docs/core-definition-files), and the
currently implemented slot/controller/variant shape. It also rejects
symlinks, special files, case-folded path collisions, unexpected folders, and
unknown SD-card payloads. The 521x165 platform graphic must be exactly 171,930
bytes with valid 16-bit brightness lanes; an optional author icon must be
exactly 36x36x16-bit and contain only documented black/white pixels.

This tree now supplies the optional author icon from a reviewable 18x18 source
grid expanded at Analogue's recommended 2x2 pixel scale. The dependency-free
[`generate_core_icon.py`](scripts/generate_core_icon.py) applies the documented
90-degree counter-clockwise storage rotation and upper-byte monochrome format;
[`generate_core_icon_test.py`](scripts/generate_core_icon_test.py) binds the
checked-in binary, upright decoded pixels, and reviewed digest. Run
`python3 scripts/generate_core_icon.py --check` before packaging. Design,
format provenance, preview instructions, and the remaining physical Pocket UI
gate are recorded in [`CORE_ICON.md`](CORE_ICON.md).

Entries are stored without DEFLATE so differing host zlib versions cannot
change the archive bytes. Every successful invocation also writes
`<archive>.provenance.json`, a deterministic sidecar that binds the archive,
raw RBF, reversed bitstream, Chip32 image, and every packaged file by byte size
and SHA-256. Repeating a package with identical inputs and the same output name
produces byte-identical ZIP and provenance files. The resulting ZIP contains
only the APF `Assets/`, `Cores/`, and `Platforms/` roots. Keep
`--output` outside `dist/`; the script enforces this so an older ZIP cannot be
included in a later package. A failed same-path rebuild removes the preceding
ZIP and provenance sidecar before validating new inputs, so stale output cannot
masquerade as success.

`make package` remains a development-package command: it can prove the exact
host inputs but cannot manufacture Quartus timing or hardware evidence. It
does not read or validate the release policy, so policy work cannot change an
otherwise identical development ZIP or provenance sidecar. A release package
can only be created through the stable assembler, which internally generates
and revalidates Release Evidence V2; the lower-level release CLI refuses direct
use.

### Signed stable-release assembly

The production path is [`assemble_stable_release.py`](scripts/assemble_stable_release.py).
It joins the existing evidence, package, and release-staging validators without
adding a second way around any gate. It accepts two complete Quartus candidate
bundles for the same exact commit and epoch. Each candidate audit must have a
GitHub attestation from a distinct `quartus-fit.yml` workflow run and a distinct
fresh job nonce. The assembler verifies both attestations, reruns both audits,
and requires byte-identical raw RBF and `build_id.mif` files. A copied bundle,
two directories carrying the same signed run identity, a rerun attempt, or a
missing identity fails closed. This establishes two distinct signed workflow
executions; it does not claim that two different physical hosts were used. The
assembler then binds the already accepted hardware manifest/inventory and the
complete known-title Pocket/Dock compatibility manifest, invokes Release
Evidence V2, invokes `package_core.py` in release mode, applies the package to
a private local staging tree with `--verify-release` semantics, and verifies
that tree again.

The default is a validated plan and creates no durable output. The checkout
must be clean and the requested output must be outside the checkout; otherwise
the output itself would invalidate the packager's exact-clean-commit proof.
Stable preflight also requires every exact checklist item in
[`RELEASE_DECISIONS.md`](RELEASE_DECISIONS.md) to be checked and rejects the
current development/blocked-release language in the release-facing README,
wiki, first-class, phase-status, and decision documents. Development packages
do not use this publication-only gate.
Run the plan first:

```sh
FINAL_COMMIT="$(git rev-parse HEAD)"
SOURCE_DATE_EPOCH="$(git show -s --format=%ct "$FINAL_COMMIT")"

python3 scripts/assemble_stable_release.py \
  --artifacts-a /private/build-a/quartus-final \
  --artifacts-b /private/build-b/quartus-final \
  --hardware-manifest /private/swan-song-qa/evidence/manifest.json \
  --hardware-inventory /private/swan-song-qa/inventory.json \
  --known-title-manifest /private/swan-song-known-titles/manifest.json \
  --output-dir /private/swan-song-release \
  --source-commit "$FINAL_COMMIT" \
  --source-date-epoch "$SOURCE_DATE_EPOCH" \
  --expected-version 1.0.0 \
  --expected-release-date YYYY-MM-DD \
  --compressed-bitstream-reviewed
```

The plan prints the exact generated `release-body.md` and its SHA-256 without
creating a durable file. Review those end-user release notes, then repeat the
exact command with both `--apply` and
`--release-body-reviewed-sha256 HASH_FROM_PLAN`. A stale or mistyped review
hash is rejected. The output directory must still not exist. Assembly occurs in one private sibling
directory and is published with a native atomic no-clobber rename only after
every validator passes. A failure removes the temporary tree and never leaves
an older or partial output under the requested name. The assembler never
publishes or changes repository settings. Its only network operation is
`gh attestation verify`, which retrieves GitHub's current official
Sigstore/TUF trust material. Verification is scoped to the repository name,
workflow path, `main` source ref, and exact source commit; the signed
certificate's run-invocation URI must match the run ID and attempt embedded in
the candidate audit. The job nonce is transitive evidence because it is inside
that signed audit. Numeric repository/owner IDs are not pinned by this gate.

The final directory contains exactly seven public files:

- the deterministically named APF release ZIP;
- its deterministic `.provenance.json` sidecar;
- a deterministic `.tar` archive of every tracked file at the exact source
  commit (the corresponding source);
- deterministic `signed-quartus-provenance.tar`, containing only the two
  candidate audit JSON files and their two GitHub attestation bundles;
- the reviewed `release-body.md`, ready to pass to GitHub CLI with
  `gh release create --notes-file` only after publication is authorized;
- `release-manifest.json`, binding both recomputed audits, signed workflow
  origins, the common RBF/build ID, accepted hardware and known-title runs,
  policy, licensing result, package, provenance, source/provenance archives,
  release body, and the hash of the generated private Release Evidence V2
  record; and
- `SHA256SUMS`, covering every public payload except itself in filename order.

Private firmware, BIOS, ROM, device identity, hardware and known-title captures,
inventories, and Release Evidence V2 files remain below the temporary private tree and are
removed from the public output before its exact inventory is checked. Retain
the original private inputs separately as release records. The checked-in
release policy and license manifest remain hard gates: the current intentional
`distribution_and_licensing_authorized: false` state makes both plan and apply
stop before assembly.

The public signed-build archive is intentionally ROM-, BIOS-, save-, and
device-identity-free. Consumers can verify both build attestations with the
official online trust root after extracting it:

```sh
mkdir -p /tmp/swan-song-signed
tar -xf signed-quartus-provenance.tar -C /tmp/swan-song-signed

gh attestation verify \
  /tmp/swan-song-signed/signed-builds/a/quartus-audit-candidate.json \
  --repo RegionallyFamous/swan-song \
  --signer-workflow github.com/RegionallyFamous/swan-song/.github/workflows/quartus-fit.yml \
  --source-digest "$FINAL_COMMIT" \
  --source-ref refs/heads/main \
  --bundle /tmp/swan-song-signed/signed-builds/a/quartus-audit-candidate.attestation.json

gh attestation verify \
  /tmp/swan-song-signed/signed-builds/b/quartus-audit-candidate.json \
  --repo RegionallyFamous/swan-song \
  --signer-workflow github.com/RegionallyFamous/swan-song/.github/workflows/quartus-fit.yml \
  --source-digest "$FINAL_COMMIT" \
  --source-ref refs/heads/main \
  --bundle /tmp/swan-song-signed/signed-builds/b/quartus-audit-candidate.attestation.json
```

`FINAL_COMMIT` must be the exact 40-hex release commit printed in the release
manifest. Direct release use of `build_release_evidence.py` and
`package_core.py --release` deliberately refuses: only the stable assembler
can carry two signed origins through Release Evidence V2 and reverify the
staged package. Their library validators remain useful to tests, but are not a
second release path. Preserve the assembler's private input bundles and
hardware inventories separately; never upload ROM, BIOS, device identity, or
private captures.

The output name must exactly match the author, shortname, version, and date in
`core.json`. Release mode also reads the checked-in
[`release-policy.json`](release-policy.json). Its V2 schema keeps the reviewed
`agg23.WonderSwan` inventory commit and 1.0.0/1.0.1 releases in an explicit
predecessor record, while the independent `RegionallyFamous.SwanSong` history
starts empty. Publisher identity and repository authorization are approved,
but distribution-and-licensing authorization remains false. Release mode
refuses either authorization failure, identity or URL drift, an existing Swan
Song tuple, and—once Swan Song has published releases—a candidate Semantic
Version or date that is not strictly later than Swan Song's own latest values.
It does not require the first Swan Song version to exceed agg23's 1.0.1. A
successful release sidecar binds the policy file by size and SHA-256. Do not
flip `distribution_and_licensing_authorized` without the required licensing,
build, and hardware review; the core metadata, policy, evidence, and archive
name must agree in one reviewed release change.

Before publication, an owner should enable GitHub immutable releases, create a
draft, attach all seven final files, and publish only after its asset inventory
matches `SHA256SUMS`. GitHub then locks the tag/assets and generates a release
attestation binding the tag, commit, and assets. After publication, verify the
release and each locally downloaded asset:

```sh
gh release verify RELEASE-TAG
gh release verify-asset RELEASE-TAG PATH-TO-DOWNLOADED-ASSET
```

Enabling immutable releases is an external repository-setting change and is
an explicit owner action; the assembler does not make it.

Licensing is an independent fail-closed gate. Every development and release
ZIP now includes `LICENSE-MANIFEST.json`, both applicable GNU GPL texts, the
two inherited MIT notices, and the APF/Intel notice records. The manifest
binds those package files by SHA-256 and rejects any file beneath the three
retired unlicensed MiSTer test roots. Their material coverage is now supplied
by project-authored generated probes.
Release mode requires `licensing_review_complete: true` with no
`review_required` item; changing only the policy boolean therefore cannot
publish a package. Validate the current evidence and blocker set with:

```sh
python3 scripts/license_manifest.py
python3 scripts/license_manifest_test.py
```

The checked-in result intentionally remains incomplete. See
[`LICENSING.md`](LICENSING.md) for the six exact blocker IDs and draft
rights-holder requests, and [`RELEASE_DECISIONS.md`](RELEASE_DECISIONS.md) for
the owner choices and final evidence sequence.

The evidence file is strict JSON with one `release_evidence` object. The
assembler-internal release validator requires magic
`SWAN_SONG_RELEASE_EVIDENCE_V2`; V1 cannot authorize a release. V2 records the
full lowercase 40-hex source commit, `source_date_epoch`, the exact Quartus Lite
version `21.1.1 Build 850`, and raw-RBF `filename`/`size`/`sha256`. Its
`build_id` entry names the sibling generated `build_id.mif` with exact size and
SHA-256; the packager also decodes its `0E0`, `0E1`, and `0E2` words and source
comments to prove they match the declared UTC epoch and commit prefix. Its
`reports` object must contain `flow`, `fit`, and `sta` entries, each naming a
sibling report with exact size and lowercase SHA-256.

V2's required `signed_build_origins` object binds two canonical candidate audit
JSON files and two GitHub attestation bundles under `signed-builds/a` and
`signed-builds/b`. Both origins must identify the same repository, workflow,
`main` ref, source commit, epoch, raw RBF, and build ID, while carrying distinct
positive signed workflow run IDs and different fresh 32-hex job nonces. The
assembler recomputes both candidate audits from their complete input bundles
before creating V2. The downstream packager recomputes the root `a` audit from
its complete sibling reports, validates both candidate documents and canonical
hashes, and reruns `gh attestation verify` for both bundles with GitHub's
official online trust roots. Each signed certificate must identify the exact
source/workflow and its run-invocation URI must match the audit's run ID and
attempt. Both audits must retain `release_eligible: false`, leave compression
unclaimed, and leave Pocket/Dock gates false. A copied directory, same signed
run identity, missing bundle, or changed candidate byte fails closed.

V2 also binds the exact accepted hardware-QA manifest and its private inventory
by filename, size, and SHA-256. Packaging reruns the full verifier, requires every physical
Pocket/Dock case and attestation to pass, and proves that the tested raw RBF,
version, date, nine-setting catalogue, and all 13 installed Pocket-facing
payloads are the release inputs. That catalogue covers every core JSON
definition, icon/info, platform definition/art, installed bitstream, and
generated Chip32 loader; packaging and release staging each reconstruct and
compare it independently.
Its separate final
`gates` object must explicitly accept all of:

- `flow_success`, `fit_success`, `setup_timing`, and `hold_timing`;
- `recovery_timing`, `removal_timing`, and `no_unconstrained_paths`;
- `no_critical_warnings`, `compressed_bitstream`, `pocket_hardware`, and
  `dock_hardware`.

The candidate audits and final release attestation are deliberately different
layers: successful fit audits never claim compression or hardware, while the
V2 release record must bind both and separately attest the reviewed
compression plus physical Pocket/Dock results. The packager verifies the exact
RBF/report/audit/bundle/QA bytes and refuses any false or missing final gate. Human
observation remains an attestation rather than mechanical proof, but bare
booleans can no longer authorize a release. The generated package-provenance
sidecar embeds the evidence manifest hash, build-ID/report/audit/QA hashes, source
identity, tool version, and accepted gates, making that reviewed evidence
cryptographically bound to the distributed ZIP.

For an unpacked SD-card tree, unzip the package at the card root. The user must
separately place legally obtained `bw.rom`, `color.rom`, and cartridge images in
`Assets/wonderswan/common/`; they are intentionally never packaged here. Both
BIOS files are required in the APF definition and have exact 4 KiB/8 KiB host
size checks; the core still independently rejects an invalid transfer length.

## Launch-hardening pull request handoff

From the repository root on the authenticated Mac, run the read-only preflight:

```sh
python3 scripts/prepare_launch_pr.py
```

It verifies `gh` authentication, the `RegionallyFamous/swan-song` origin and
GitHub repository, the local/remote base, and the exact launch-hardening change
allowlist. A separate explicit preservation list protects the existing local
hardware, macOS, build-output, dependency, and adjacent-project paths: the
command warns about them, never stages them, and proves they remain untracked
after the commit. It rejects every other tracked or untracked path and never
uses `git add .`.

To perform the handoff, add `--apply` and type the displayed confirmation
exactly:

```sh
python3 scripts/prepare_launch_pr.py --apply
```

Apply mode fetches `origin/main`, proves the current `HEAD` tree is identical
to that fetched tree before switching, creates `codex/launch-hardening`, stages
only the allowlisted paths, verifies the staged status and whitespace, commits,
pushes without force, and opens the pull request with `gh`. It intentionally
stops before merge and does not create or publish a release.
