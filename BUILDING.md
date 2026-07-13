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
  A self-contained WSC probe streams four addressed bytes from linear ROM at
  the 24 kHz setting and requires the exact SDMA values, offsets, initiator,
  origin status, and 128-CPU-clock cadence. The inherited DMA bus reports its
  raw `byte_enable=3` while SDMA still advances one byte per transfer, so the
  trace contract does not treat that mask as SDMA sample width. This probe does
  not establish the physical `117 mod 128` phase or `6+N` stolen-cycle cost.
- Paired generated 2 MiB mapper probes runtime-verify `boot_rom`,
  `cart_sram`/`absent_sram`, mono `unmapped`, `cart_rom0`, `cart_rom1`, and
  `cart_rom_linear` classification. Exact checks cover C0/C1 bank bits that
  survive their masks, C1 wrap through a declared 128 KiB SRAM, even-word and
  odd-byte writes, ROM aliases, resolved offsets, instruction origins, and the
  current core's readback values. Separate generated 4 KiB/8 KiB boot images
  prove mono and Color overlay offsets, execution from byte zero, a low-window
  marker read, A0 lockout, and the same top addresses becoming cartridge ROM.
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

- Docker (for pinned `ghdl/ghdl:6.0.0-llvm-ubuntu-24.04`)
- Verilator 5.x
- a C++17 compiler
- Python 3

Run the regression suite:

```sh
make regression
```

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
and `bg_cell` event classes. `translate_vhdl.sh` sets the compile-time `SwanTop.is_simu`
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
  --trace-events cpu,bank,vram,mem,bg_cell \
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
capture to check all five CSV schema versions, event-specific fields, monotonic cycles,
`CS:IP` to physical-PC conversion, and requested PC/address/role containment.
The same regression generates (but does not check in) minimal open bank-write,
WSC GDMA/SDMA, dual-format 4bpp, paired mapper-memory, and mono/Color
boot-overlay probes. The GDMA
probe requires two known ROM words to appear in the ordered completed
read/write events at their resolved ROM and IRAM offsets. The SDMA probe
requires four byte-addressed linear-ROM reads, including odd addresses, at the
fastest documented cadence through the runtime `sdma` filter. The mapper probes
require complete unfiltered memory history, exact values and resolved offsets,
issued write lane masks plus the CPU-read zero convention, and exact
instruction origins for probe-owned accesses across the paired trace-space
coverage.
The boot probes bind both input images and prove the overlay-to-cartridge
transition at identical physical addresses.
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
`.ws`, `.wsc`, `.rom`, and `.sav` files, and writes entries in sorted order with
fixed timestamps. Entries are stored without DEFLATE so differing host zlib
versions cannot change the archive bytes. The resulting ZIP therefore contains
the APF `Assets/`, `Cores/`, and `Platforms/` roots and is reproducible for
identical inputs. Keep
`--output` outside `dist/`; the script enforces this so an older ZIP cannot be
included in a later package. A failed same-path rebuild removes the preceding
ZIP before validating new inputs, so stale output cannot masquerade as success.

For an unpacked SD-card tree, unzip the package at the card root. The user must
separately place legally obtained `bw.rom`, `color.rom`, and cartridge images in
`Assets/wonderswan/common/`; they are intentionally never packaged here.
