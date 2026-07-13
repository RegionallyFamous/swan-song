# Building and testing Swan Song

## What is currently verified

- GHDL 6.0.0 successfully analyzes and translates the VHDL console hierarchy.
- Verilator 5.050 successfully elaborates, compiles, and runs that translation.
- The open MiSTer sprite-priority and window test ROMs produce deterministic
  224×144 PNG frame hashes in repeated runs.
- Wonderful's open WSC extended-range fixture renders all three PASS fields and
  proves that 2bpp Color mode fetches its map, bank-1 tiles, and sprite table
  above 16 KiB without aliasing; all 15,794 physical display reads match
  provenance (15,608 exact CPU-written words and 186 power-up prefetches).
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
  row, and every final RGB pixel. All 25,111 display reads match the
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
  sprite-list order without Screen 2. Its strict two-frame gate proves 24
  descriptor words, 96 sprite-tile reads, 48 packed 4bpp row promotions, 64
  exact GDMA words, 18 final CPU writes, zero display collisions, and a stable `frame-1.rgb` SHA-256 of
  `eb515b9c58a3fc7f386520937818d95b846a94cd43a86edef1daf54f3a4b5ef4`.
- The title-agnostic glyph reporter converts atomic-cell provenance into a
  complete deterministic epoch CSV plus a compact labeled PNG. On that fixture
  it retains 592 placement/provenance epochs while surfacing seven distinct
  exact bitmaps; six bind to the expected maps, writers, IRAM ranges, and ROM
  source ranges. It never assigns character identity from tile numbers alone.
- The structured-trace config parser and CSV/JSONL serializers have a standalone
  C++ unit test. The regression also validates CPU, display-RAM, and completed
  memory events from the
  translated model, including `CS:IP` conversion, inclusive PC/address filters,
  exact CPU memory origins, exact C0-C3 mapper-write instruction origins,
  resolved mapper offsets, completion-aligned display words/collision status,
  and all six screen-map/tile and sprite-table/tile roles.
  A byte-lane correlator independently reconstructs all 78,940 fetched words
  from complete IRAM history. In that bootstrap trace, its conservative CPU
  ROM-to-IRAM classifier requires a trace-observed `F3 A4` origin signature
  plus an immediate exact same-instruction byte transfer. It accepts two
  2,048-byte chains—ROM `0x00252..0x00a51` to IRAM `0x2800..0x2fff` and ROM
  `0x00a52..0x01251` to IRAM `0x2000..0x27ff`—for 4,096 bytes, two origins,
  52,512 display words, and 26,222 atomic cells whose contributing tile-row
  bytes are MOVSB-sourced. The extended-range and
  Shift-JIS fixtures report zero in all four categories; `unattributed` alone
  is not treated as proven prefetch. A dedicated verifier binds the open ROM,
  complete v5 manifest, opcode bytes, uninterrupted alternating transaction
  chains, address progression, byte lanes, and every copied byte. The suite
  also generates build-only
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
  the exact v5 prefix and is emitted only when `sprite_row` is requested. The translated
  ROM regression validates 26,224 bootstrap cells across both layers and 5,176
  extended-range Color cells. The Shift-JIS workload adds 8,307 Screen 1 cells,
  including 96 manifest-bound Japanese glyph-row promotions. The generated
  planar and packed workloads add 8,493 Screen 1 4bpp cells apiece, including
  64 exact diagnostic rows per encoding. All five runs
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
  ready, `1` not allowed ever, or `2` check later. Slot 0 accepts only
  power-of-two ROMs from 64 KiB through the implemented 16 MiB mapper limit;
  slots 9 and 10 accept exactly 4 KiB and 8 KiB firmware respectively; slot 11
  accepts only absent, cartridge-canonical, or supported legacy EEPROM-save
  lengths once footer metadata is ready. Focused benches cover direction,
  unknown IDs, boundary sizes, retry-to-ready transitions, and malformed
  lengths.
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
  on ambiguous source identity. Two identical Quartus RBFs have not yet been
  produced on a supported host.
- The reverse-bit and deterministic APF package scripts are host-independent.
  Packaging materializes the core's required 259-byte `chip32.bin` offline,
  verifies both its assembly-source and image identities, and rejects missing,
  changed, or path-escaping core references. The image is byte-identical to the
  one in agg23's 1.0.1 release.
- Quartus compilation and timing closure have not been run in this fork; the
  current macOS host cannot run supported Quartus 21.1.1.
- No build has been confirmed on an Analogue Pocket in this fork.

## Simulation

Requirements:

- Docker (for the GHDL translation image)
- Verilator 5.x
- a C++17 compiler
- Python 3
- Tcl (`tclsh`, for the reproducible build-ID contract)

Run the regression suite:

```sh
make regression
```

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
| 0 | Cartridge | Write only; power of two, 64 KiB through 16 MiB; APF persists the selected filename and performs a full core reload when it changes |
| 9 | Mono BIOS | Required write-only APF asset; exactly 4,096 bytes |
| 10 | Color BIOS | Required write-only APF asset; exactly 8,192 bytes |
| 11 | Save | Read becomes ready only after `reset_n=0`, synchronized execution has stopped, and a fixed 31-`clk_74a` drain guard has elapsed, with startup metadata/table/init still valid; write accepts absent (zero), canonical for the current cartridge, or legacy 2,060-byte RTC EEPROM type `10`/`50` |

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
old title before Chip32 derives and loads the new title's save. Framework 2.3
is the minimum because its **Reset all to defaults** behavior correctly clears this
browser history.

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
documents known values through 16 MiB, while its [mapper
documentation](https://ws.nesdev.org/wiki/Mapper) shows six 1 MiB linear-bank
bits for the later Bandai 2003 mapper, implying 64 MiB of theoretical address
capacity. This core implements a 24-bit ROM address and therefore rejects
anything above 16 MiB. The [Wonderful WonderSwan target
documentation](https://wonderful.asie.pl/docs/target/wswan/) is the modern
toolchain reference used by the open generated-ROM validation; it does not
raise the core's implemented limit.

### Supported Pocket launch boundary

The packaged product is an openFPGA SD-card asset launcher for `.ws` and `.wsc`
images with both legally obtained BIOS files. It uses APF for data slots,
video, audio, input, saves, settings, and Dock transport. It does not enable
Pocket's physical cartridge adapter or link port, does not participate in the
first-party physical-cartridge/Library launch flow, and does not bundle BIOS or
commercial game data.

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

### Exact CI toolchain

The GitHub regression workflow runs the same `make regression` entry point but
does not install a moving Ubuntu package. It pins:

- [`actions/checkout` v4.3.1](https://github.com/actions/checkout/commit/34e114876b0b11c390a56381ad16ebd13914f8d5)
  by full commit SHA `34e114876b0b11c390a56381ad16ebd13914f8d5`;
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
remain the behavioral drift gate. No successful remote run is claimed until
this branch is pushed to a configured repository.

Run a ROM for six frames and emit PNGs:

```sh
./sim/verilator/run.sh \
  --rom testroms/windowtest/windowtest.ws \
  --frames 6 \
  --out build/sim/windowtest
```

Add `--trace build/sim/windowtest.vcd` for a VCD or `--bios /path/to/bw.rom`
to test with a legally obtained firmware image. Without `--bios`, the harness
programs a nine-byte open bootstrap suitable for the included test ROMs. The
harness never searches for or downloads firmware.

### Structured event traces

The VCD option captures the whole translated design. For a smaller,
machine-readable stream, select one or more of the `cpu`, `bank`, `vram`, `mem`,
`bg_cell`, and `sprite_row` event classes. `translate_vhdl.sh` sets the compile-time `SwanTop.is_simu`
generic for this simulator build; the production default leaves it disabled.

```sh
./sim/verilator/run.sh \
  --rom testroms/windowtest/windowtest.ws \
  --frames 6 \
  --event-trace build/sim/windowtest.csv \
  --trace-events bank,vram
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
It also runs `correlate_provenance.py` against an unfiltered-from-reset
memory/display capture and requires every fetched word to be exact: no value
mismatch, mixed-port collision, partial word, or unobserved byte is accepted.
For CPU ROM sources, instruction ownership is only a prerequisite: the
correlator also requires the observed `F3 A4` origin signature and an immediate
same-instruction ROM-read/IRAM-byte-write pair with an exact destination and
matching low byte. It does not infer prefetch from an `unattributed` row alone.
`verify_cpu_rep_movsb.py` separately locks the bootstrap claim to the canonical
open ROM and rejects incomplete, interleaved, discontinuous, or extra
ROM-to-IRAM instruction chains.
The v5 path additionally runs `correlate_bg_cells.py`: it independently groups
Screen 1/2 map and tile reads, validates each promoted atomic background cell,
and preserves the writers observed on the raw-fetch edge rather than consulting
IRAM at the later promotion edge. Across the open-ROM suite it requires nonzero
coverage from both screen layers. This proves the promoted map and contributing tile row, not that any
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

Generated VHDL-to-Verilog files, binaries, traces, raw RGB frames, and PNGs live
under `build/` and are ignored by Git.

## Quartus

The checked-in project records Quartus 18.1.1 as its original version and
21.1.1 Lite as its last-saved version; `ap_core.qpf` still declares 18.1. The
build helper expects 21.1.1, but this fork has not compiled the project. It
targets Cyclone V device `5CEBA4F23C8`; Quartus Lite is supported on Linux and
Windows, not this macOS workstation.

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
Quartus. Phase 0 still requires two clean Quartus 21.1.1 builds with identical
RBF hashes, successful fitter/TimeQuest reports, and the separately authorized
hardware check.

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
image only after `src/support/chip32.asm` and the decoded 259-byte image match
their pinned SHA-256 identities. It requires no network access or host
assembler. The encoded image is the exact output of the official
[open-fpga/bass-chip32 v1.0.0](https://github.com/open-fpga/bass-chip32/releases/tag/v1.0.0)
for the checked-in assembly and matches
[agg23's WonderSwan 1.0.1 package](https://github.com/agg23/openfpga-wonderswan/releases/tag/1.0.1):
`ca7a2b11c11250b4842c1853d6d500c0289e7065db479c11fde37c130440a81c`.
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
must additionally use `--release` and `--build-evidence`:

```sh
./scripts/package_core.py \
  --rbf src/fpga/output_files/ap_core.rbf \
  --build-evidence build/release-evidence.json \
  --release \
  --output build/Author.Core_version_YYYY-MM-DD.zip
```

The output name must exactly match the author, shortname, version, and date in
`core.json`. Release mode also reads the checked-in
[`release-policy.json`](release-policy.json), which pins the reviewed public
inventory commit, publisher identity and repository URL, plus every published
version/date pair. It refuses an unauthorized publisher, identity or URL drift,
an existing tuple, a candidate Semantic Version that is not strictly newer than
the public latest, and a date that is not strictly later than the public latest.
A successful release sidecar binds the policy file by
size and SHA-256. The checked-in policy deliberately has `authorized: false`:
do not merely flip it. Release ownership must first be resolved as either an
authorized upstream continuation or a separately authored core, after which
the core folder, metadata, policy, and new version/date must agree in one
reviewed change.

The evidence file is strict JSON with one `release_evidence` object. It records
magic `SWAN_SONG_RELEASE_EVIDENCE_V1`, the full lowercase 40-hex source commit,
`source_date_epoch`, a Quartus version beginning `21.1.1`, and raw-RBF
`filename`/`size`/`sha256`. Its `build_id` entry names the sibling generated
`build_id.mif` with exact size and SHA-256; the packager also decodes its `0E0`,
`0E1`, and `0E2` words and source comments to prove they match the declared UTC
epoch and commit prefix. Its `reports` object must contain `flow`, `fit`, and
`sta` entries, each naming a sibling `.flow.rpt`, `.fit.rpt`, or `.sta.rpt` with
exact size and lowercase SHA-256; every report must be nonempty and identify
Quartus 21.1.1. Its `gates` object must explicitly accept all of:

- `flow_success`, `fit_success`, `setup_timing`, and `hold_timing`;
- `recovery_timing`, `removal_timing`, and `no_unconstrained_paths`;
- `no_critical_warnings`, `compressed_bitstream`, `pocket_hardware`, and
  `dock_hardware`.

The packager verifies the exact RBF/report bytes and refuses any false or
missing gate. The booleans are a review attestation, not an unreliable attempt
to scrape every localized Quartus report format: the release reviewer remains
responsible for TimeQuest, warnings, fit/resource changes, and the recorded
Pocket/Dock runs. The generated package-provenance sidecar embeds the evidence
manifest hash, build-ID/report hashes, source identity, tool version, and
accepted gates, making that reviewed evidence cryptographically bound to the
distributed ZIP.

For an unpacked SD-card tree, unzip the package at the card root. The user must
separately place legally obtained `bw.rom`, `color.rom`, and cartridge images in
`Assets/wonderswan/common/`; they are intentionally never packaged here. Both
BIOS files are required in the APF definition and have exact 4 KiB/8 KiB host
size checks; the core still independently rejects an invalid transfer length.
