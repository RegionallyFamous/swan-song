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
- The native open Shift-JIS fixture renders `日本語かな漢` from licensed Misaki
  rows and proves 48 exact GDMA word transfers (48 ROM reads paired with 48
  tile-RAM writes), six exact CPU map writers, two promotions of every glyph
  row, and every final RGB pixel. All 25,111 display reads match the
  reset-complete writer scoreboard.
- The structured-trace config parser and CSV/JSONL serializers have a standalone
  C++ unit test. The regression also validates CPU, display-RAM, and completed
  memory events from the
  translated model, including `CS:IP` conversion, inclusive PC/address filters,
  exact CPU memory origins, exact C0-C3 mapper-write instruction origins,
  resolved mapper offsets, completion-aligned display words/collision status,
  and all six screen-map/tile and sprite-table/tile roles.
  A byte-lane correlator independently reconstructs all 78,940 fetched words
  from complete IRAM history. The suite also generates build-only
  ROMs that verify all C0-C3 bank writes with their owning instruction IDs/PCs,
  including both accepted byte writes from one word `OUT`, and an exact GDMA
  ROM-to-IRAM chain.
- The translated trace runtime covers CPU and GDMA memory transactions. The
  schema reserves `sdma`, but `is_simu=1` suppresses sound-DMA bus traffic, so
  no SDMA runtime coverage is claimed.
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
- V5 atomic Screen 1/2 background-cell serialization, map/tile decode, 2bpp
  selected-word versus 4bpp two-word handling, collision semantics, and
  fetch-time writer snapshots pass focused C++/Python fixtures. The translated
  ROM regression validates 26,224 bootstrap cells across both layers and 5,176
  extended-range Color cells. The Shift-JIS workload adds 8,307 Screen 1 cells,
  including 96 manifest-bound Japanese glyph-row promotions. All three runs
  account explicitly for superseded and end-of-capture prefetches.
- A pinned Wonderful-toolchain `initfini` ROM boots reproducibly, renders its
  constructor-pass checkmark, and produces identical traces and final frames in
  two runs. See `WONDERFUL_VALIDATION.md` for the exact source, toolchain, and
  hashes; the generated ROM is not checked in.
- The reverse-bit and deterministic APF package scripts are host-independent.
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
WSC GDMA, paired mapper-memory, and mono/Color boot-overlay probes. The GDMA
probe requires two known ROM words to appear in the ordered completed
read/write events at their resolved ROM and IRAM offsets. The mapper probes
require complete unfiltered memory history, exact values and resolved offsets,
issued write lane masks plus the CPU-read zero convention, and exact
instruction origins for probe-owned accesses across the paired trace-space
coverage.
The boot probes bind both input images and prove the overlay-to-cartridge
transition at identical physical addresses.
It also runs `correlate_provenance.py` against an unfiltered-from-reset
memory/display capture and requires every fetched word to be exact: no value
mismatch, mixed-port collision, partial word, or unobserved byte is accepted.
The v5 path additionally runs `correlate_bg_cells.py`: it independently groups
Screen 1/2 map and tile reads, validates each promoted atomic background cell,
and preserves the writers observed on the raw-fetch edge rather than consulting
IRAM at the later promotion edge. Across the open-ROM suite it requires nonzero
coverage from both screen layers. This proves the promoted map and contributing tile row, not that any
specific pixel survived windows, transparency, priority, sprites, or clipping.
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

The script copies `dist/`, writes the reversed stream as the filename declared
by `core.json` (`wonderswan.rev`), rejects `.ws`, `.wsc`, `.rom`, and `.sav`
files, and writes entries in sorted order with fixed timestamps. The resulting
ZIP therefore contains the APF `Assets/`, `Cores/`, and `Platforms/` roots and
is reproducible for identical inputs. Keep `--output` outside `dist/`; the
script enforces this so an older ZIP cannot be included in a later package.

For an unpacked SD-card tree, unzip the package at the card root. The user must
separately place legally obtained `bw.rom`, `color.rom`, and cartridge images in
`Assets/wonderswan/common/`; they are intentionally never packaged here.
