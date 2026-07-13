# Wonderful toolchain validation

This record covers one open-source Wonderful toolchain ROM executed by the
Swan Song system simulator on 2026-07-12. It does not establish Quartus timing
closure or behavior on an Analogue Pocket.

## Source and build provenance

- Repository: <https://github.com/asiekierka/ws-test-suite>
- Commit: `7dfa0e2e869d08386b685d6a56df0bcfaf181b47`
- Test source: `src/wonderful/libc/initfini/main.c`
- Configuration: `src/wonderful/libc/initfini/wfconfig.toml`
- License: MIT, Copyright (c) 2023 Adrian "asie" Siekierka; the pinned
  repository's `LICENSE` SHA-256 is
  `266d82632cf7ed13f791b599ef6839d3c525f9f6eecfbe36e61dd1f01e77ca38`.
- Upstream CI image: `cbrzeszczot/wonderful:wswan-latest`. The locally cached
  image used while recording this validation resolves to
  `cbrzeszczot/wonderful@sha256:1bd074214c0592a5fca3f26ce0c47d3a809f48e83f68705189fe30c78e75435e`.
  The tag is mutable; use the digest to reproduce this environment.

The relevant installed Wonderful packages were:

| Package | Version |
| --- | --- |
| `target-wswan` | `0.1.0-3` |
| `target-wswan-syslibs` | `0.2.0.r254.d7d97ce-1` |
| `toolchain-gcc-ia16-elf-binutils` | `2.43.1.r119451.5cc0e071551-1` |
| `toolchain-gcc-ia16-elf-gcc` | `6.3.0.r147159.e7507d1845e-1` |
| `toolchain-gcc-ia16-elf-gcc-libs` | `6.3.0.r147159.e7507d1845e-1` |
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

The resulting 131,072-byte ROM used for both runs had SHA-256
`f6f24b8dc7f1cd4eac0005e208d9e17ccd278419df5402cfa8d22e84dd9bb347`.
The ROM is not checked into Swan Song.

## Simulator evidence

The already-built Verilator model was invoked twice, without rebuilding or
retranslating between runs:

```sh
build/sim/obj_dir/VSwanTop \
  --rom upstream/ws-test-suite/build/roms/wonderful/libc/initfini.ws \
  --frames 6 --max-cycles 4000000 \
  --out build/sim/wonderful-initfini-a \
  --event-trace build/sim/wonderful-initfini-a/events.csv \
  --trace-events cpu,bank,vram

build/sim/obj_dir/VSwanTop \
  --rom upstream/ws-test-suite/build/roms/wonderful/libc/initfini.ws \
  --frames 6 --max-cycles 4000000 \
  --out build/sim/wonderful-initfini-b \
  --event-trace build/sim/wonderful-initfini-b/events.csv \
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
| Structured trace SHA-256 | `bb58f4bda9650fd1a4f9e24b282cbb9ba85843c6c227c5655f2d529a937314b0` |
| CPU events | 47,198 |
| VRAM events | 2,163,360 |
| Bank-register events | 0 |
| Total events | 2,210,558 |
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
the true value; failure renders tile 6 (an X). The result therefore verifies
that this pinned Wonderful-generated ROM entered its CRT, ran its constructor,
entered main, initialized the text display, and reached its terminal loop in
the translated system model.
