# Building and testing Swan Song

## What is currently verified

- GHDL 6.0.0 successfully analyzes and translates the VHDL console hierarchy.
- Verilator 5.050 successfully elaborates, compiles, and runs that translation.
- The open MiSTer sprite-priority and window test ROMs produce deterministic
  224×144 PNG frame hashes in repeated runs.
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
