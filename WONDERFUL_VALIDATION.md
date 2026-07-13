# Wonderful toolchain validation

This record covers open-source Wonderful toolchain ROMs executed by the Swan
Song system simulator. The original 2026-07-12 record below preserves the
pinned `initfini` result; the current medium-SRAM regression is recorded at the
end. Neither establishes Quartus timing closure or Analogue Pocket behavior.

## Source and build provenance

- Repository: <https://github.com/asiekierka/ws-test-suite>
- Commit: `7dfa0e2e869d08386b685d6a56df0bcfaf181b47`
- Test source: [pinned `main.c`](https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/src/wonderful/libc/initfini/main.c)
- Configuration: [pinned `wfconfig.toml`](https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/src/wonderful/libc/initfini/wfconfig.toml)
- License: MIT, Copyright (c) 2023 Adrian "asie" Siekierka; the pinned
  [repository license](https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/LICENSE) SHA-256 is
  `266d82632cf7ed13f791b599ef6839d3c525f9f6eecfbe36e61dd1f01e77ca38`.
- Upstream CI image: `cbrzeszczot/wonderful:wswan-latest`. The locally cached
  image used while recording this validation resolves to
  `cbrzeszczot/wonderful@sha256:1bd074214c0592a5fca3f26ce0c47d3a809f48e83f68705189fe30c78e75435e`.
  The tag is mutable; the digest below is the reproducible build input.

The pinned digest contains these relevant Wonderful packages:

| Package | Version |
| --- | --- |
| `target-wswan` | `0.1.0-3` |
| `target-wswan-syslibs` | `0.2.0.r253.99bf066-1` |
| `toolchain-gcc-ia16-elf-binutils` | `2.43.1.r119450.cb9b8d4a0ad-2` |
| `toolchain-gcc-ia16-elf-gcc` | `6.3.0.r147156.aeca9aa010a-1` |
| `toolchain-gcc-ia16-elf-gcc-libs` | `6.3.0.r147156.aeca9aa010a-1` |
| `wf-tools-native` | `0.1.0.r180.3bf0d29-1` |
| `wf-tools-lua` | `0.1.0.r181.7f5f3f9-1` |

Build the selected ROM from the pinned checkout with the recorded container:

```sh
docker run --rm --platform linux/amd64 \
  -v "$PWD/upstream/ws-test-suite:/work" -w /work \
  cbrzeszczot/wonderful@sha256:1bd074214c0592a5fca3f26ce0c47d3a809f48e83f68705189fe30c78e75435e \
  make WONDERFUL_TOOLCHAIN=/opt/wonderful \
  build/roms/wonderful/libc/initfini.ws
```

This intentionally does not run `wf-pacman -Syu`: upstream CI updates packages
from a mutable repository before building. A fresh temporary checkout built
with the exact digest and command above reproduced the ROM hash below.

The resulting 131,072-byte ROM used for both runs had SHA-256
`f6f24b8dc7f1cd4eac0005e208d9e17ccd278419df5402cfa8d22e84dd9bb347`.
The ROM is not checked into Swan Song.

## Simulator evidence

The tested Swan Song revision was
`32eb4d357ed3a6751d07278161aee33b66c6136b`, translated with GHDL 6.0.0 and
compiled with Verilator 5.050. `make regression` first rebuilt and validated the
model. That same binary was then invoked twice without rebuilding between runs:

```sh
make regression

build/sim/obj_dir/VSwanTop \
  --rom upstream/ws-test-suite/build/roms/wonderful/libc/initfini.ws \
  --frames 6 --max-cycles 4000000 \
  --out build/sim/wonderful-v2-a \
  --event-trace build/sim/wonderful-v2-a/events.csv \
  --trace-events cpu,bank,vram

build/sim/obj_dir/VSwanTop \
  --rom upstream/ws-test-suite/build/roms/wonderful/libc/initfini.ws \
  --frames 6 --max-cycles 4000000 \
  --out build/sim/wonderful-v2-b \
  --event-trace build/sim/wonderful-v2-b/events.csv \
  --trace-events cpu,bank,vram
```

Raw frames were converted with `sim/verilator/rgb_to_png.py`. Both runs
produced the same values:

| Artifact or observation | Result |
| --- | --- |
| Frames completed | 6 |
| Frames 1 through 5, raw RGB SHA-256 | `0a6e2f5abc55357144a8827b2b51c84e9cff0819a1ff3a098371c1098fb80684` |
| Frames 1 through 5, PNG SHA-256 | `aea0da7ae125a0bd055647d1bedbbb5839415319dd8aae554f489ad5bde8afbf` |
| PNG dimensions | 224 x 144, 8-bit RGB |
| Structured trace schema | v2 CSV: eight columns with appended VRAM role |
| Structured trace SHA-256 | `0b93a41eec6dde1b9add75f0a7d114bbcb54a72b649cc1f575e5a9a60738d86c` |
| CPU events | 47,198 |
| Active display-memory events | 71,346 |
| `screen1_map` / `screen1_tile` | 23,776 / 47,552 |
| `sprite_table` | 18 |
| Screen 2 / sprite-tile events | 0 / 0, as expected for this test |
| Bank-register events | 0 |
| Total events | 118,544 |
| Final CPU location | physical PC `0xff68b`, the test's terminal loop |

The two trace files were byte-identical. Frame 0 was the blank startup frame;
frames 1 through 5 were byte-identical within and across runs. Zero bank writes
are expected because this 128 KiB ROM executes from the fixed upper cartridge
window and does not program C0-C3.

Visual inspection of each final frame found black `init` text at the upper
left and a black checkmark at the upper right on an otherwise white screen.
That checkmark has program-level pass semantics: the test initializes
`constructed` to false, sets it true in a function marked
`__attribute__((constructor))`, and renders pass tile 5 only when main observes
the true value; the pinned [pass/fail helper](https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/common/test/pass_fail.h)
renders tile 6 (an X) on failure. The result therefore verifies
that this pinned Wonderful-generated ROM entered its CRT, ran its constructor,
entered main, initialized the text display, and reached its terminal loop in
the translated system model.

## Current medium-SRAM regression (2026-07-13)

The repository now carries a second, deterministic Wonderful-generated open
ROM and source under
[`testroms/swan-song/wonderful_medium_sram`](testroms/swan-song/wonderful_medium_sram/README.md).
It uses the current `wswan/medium-sram` target, system libraries at
`d7d97ce9490c54aff3ad8ad5f4b60f1c547757ab`, and example scaffold at
`811b739ab1f0203336a08da8db34365d29869617`.

`make regression` binds its exact source and 131,072-byte ROM hash, the CRT's
DS=`1000h` SRAM selection, `.bss` zeroing, `.data=0x5AA5` initialization, far
jump to `main`, exact program mutation/readback to `0xA55A`/`0xC33C`, the
successful `MEDIUM-SRAM OK` console cells, terminal HLT, and final raw RGB
SHA-256 `3d4dc04e7d09202bd36b2401600bdb00c4489b89888bd7e4c52520a3e7e0c10b`.
The focused verifier rejects source and ROM mutations.

The complete targeting guidance is in
[`HOMEBREW_WONDERWITCH.md`](HOMEBREW_WONDERWITCH.md). Current Wonderful can
assemble `.fx` files with its pinned clean-room AthenaOS into an ordinary `.ws`;
Swan Song now boots that read-only `mkrom` path and executes BIOS text/input
services in the translated system model. The separately reproducible result is
recorded in [`WONDERWITCH_VALIDATION.md`](WONDERWITCH_VALIDATION.md). Writable
flash/port-`CEh`, direct `.fx` APF loading, and Pocket hardware remain unclaimed,
and no firmware is bundled.
