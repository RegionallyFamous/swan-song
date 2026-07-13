# Building and testing Swan Song

## What is currently verified

- GHDL 6.0.0 successfully analyzes and translates the VHDL console hierarchy.
- Verilator 5.050 successfully elaborates, compiles, and runs that translation.
- The open MiSTer sprite-priority and window test ROMs produce deterministic
  224×144 PNG frame hashes in repeated runs.
- The structured-trace config parser and CSV/JSONL serializers have a standalone
  C++ unit test. The regression also validates CPU, display-RAM, and completed
  memory events from the
  translated model, including `CS:IP` conversion, inclusive PC/address filters,
  exact CPU memory origins, resolved mapper offsets, completion-aligned display
  words/collision status, and all six screen-map/tile and sprite-table/tile roles.
  A byte-lane correlator independently reconstructs all 78,760 fetched words
  from complete IRAM history. The suite also generates build-only
  ROMs that verify all C0-C3 bank writes and an exact GDMA ROM-to-IRAM chain.
- A pinned Wonderful-toolchain `initfini` ROM boots reproducibly, renders its
  constructor-pass checkmark, and produces identical traces and final frames in
  two runs. See `WONDERFUL_VALIDATION.md` for the exact source, toolchain, and
  hashes; the generated ROM is not checked in.
- The reverse-bit and deterministic APF package scripts are host-independent.
- Quartus compilation and timing closure are **not verified on this macOS host**.
- No build has been confirmed on an Analogue Pocket in this fork.

## Simulation

Requirements:

- Docker (for pinned `ghdl/ghdl:6.0.0-llvm-ubuntu-24.04`)
- Verilator 5.x
- a C++17 compiler
- Python 3

Run the two-image regression:

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
machine-readable stream, select one or more of the `cpu`, `bank`, `vram`, and `mem`
event classes. `translate_vhdl.sh` sets the compile-time `SwanTop.is_simu`
generic for this simulator build; the production default leaves it disabled.

```sh
./sim/verilator/run.sh \
  --rom testroms/windowtest/windowtest.ws \
  --frames 6 \
  --event-trace build/sim/windowtest.csv \
  --trace-events bank,vram
```

CPU records can be limited to an inclusive 20-bit physical-PC range. The range
applies only to CPU events, so bank and VRAM activity remains available in a
mixed trace:

```sh
./sim/verilator/run.sh \
  --rom /path/to/legally-obtained-title.wsc \
  --frames 10 \
  --event-trace build/sim/text-renderer.jsonl \
  --trace-events cpu,bank,vram,mem \
  --trace-pc 0x80000-0x8ffff \
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
capture to check all four CSV schema versions, event-specific fields, monotonic cycles,
`CS:IP` to physical-PC conversion, and requested PC/address/role containment.
The same regression generates (but does not check in) minimal open bank-write
and WSC GDMA probes. The latter requires two known ROM words to appear in the
ordered completed read/write events at their resolved ROM and IRAM offsets.
It also runs `correlate_provenance.py` against an unfiltered-from-reset
memory/display capture and fails on any non-collision fetched-word mismatch.

Generated VHDL-to-Verilog files, binaries, traces, raw RGB frames, and PNGs live
under `build/` and are ignored by Git.

## Quartus

The checked-in project was created for Quartus Prime Lite 21.1.1 and targets
Cyclone V device `5CEBA4F23C8`. Quartus Lite is supported on Linux and Windows,
not this macOS workstation.

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
