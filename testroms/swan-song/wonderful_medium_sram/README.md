# Wonderful medium-SRAM fixture

This open WonderSwan Color ROM exercises a modern Wonderful configuration that
the prior Swan Song fixtures did not: `wswan/medium-sram` with a 32 KiB
cartridge-SRAM data segment. It verifies a minimally adapted, pinned Wonderful
CRT's ROM-to-SRAM `.data` copy, SRAM `.bss` clear, far-code entry into `main`,
far ROM strings, current `libws`/`libwse`/`libwsx` console setup, and read/write
access through DS=`1000h`.

The source starts with `initialized_word = 0x5AA5` and an uninitialized
`zero_word`. `main` explicitly enables Color mode, requires the CRT-provided
values, changes them to `0xA55A` and `0xC33C`, reads both back, and renders
`MEDIUM-SRAM OK` only if the mode transition and all four memory checks pass.
The regression binds the exact SRAM events, successful branch, terminal HLT,
map cells, and final raster.

The Color header and local [`src/crt0_color.s`](src/crt0_color.s) are
intentional. With `SRAM_32KB`, Wonderful 0.2.0 places `__wf_heap_top` at
`8000h` while SS remains console IRAM. Its stock SRAM CRT then clears System
Control 2 bit 7 before its first push, temporarily restricting CPU IRAM access
to the mono-compatible 16 KiB window and making that high stack inaccessible.

The local zlib-derived CRT is a deliberately small adaptation of the pinned
upstream source. Before selecting SP=`8000h`, it checks physical Color-model
capability through `$A0.1`, halts if Color hardware is absent, and sets `$60.7`
to expose the upper Color IRAM. It never clears that bit before constructors or
`main`; `main` still requests Color mode as its first source-level statement.
An SP=`4000h` workaround was also tested. It avoided unmapped accesses, but the
stack collided with the console/font workspace and console initialization did
not return, so preserving the normal high stack with an early Color enable is
the validated fixture behavior.
The exact source, machine-code ordering, SRAM events, and frames are mutation
locked by the regression. See
[`HOMEBREW_WONDERWITCH.md`](../../../HOMEBREW_WONDERWITCH.md).

## Provenance and rebuild

The build skeleton and console setup are adapted from the CC0
[Wonderful examples](https://github.com/WonderfulToolchain/target-wswan-examples)
at commit `811b739ab1f0203336a08da8db34365d29869617`. The linked runtime is from
[target-wswan-syslibs](https://codeberg.org/WonderfulToolchain/target-wswan-syslibs)
at commit `d7d97ce9490c54aff3ad8ad5f4b60f1c547757ab` and is covered by the adjacent
zlib notice. The local CRT is plainly marked as an altered copy of
[that exact upstream file](https://codeberg.org/WonderfulToolchain/target-wswan-syslibs/src/commit/d7d97ce9490c54aff3ad8ad5f4b60f1c547757ab/crts/src/crt0.s)
and retains its complete license header. The probe changes and verifier are
Swan Song project work under the fixture's CC0 terms; no BIOS, WonderWitch
firmware, or commercial data is present.

The checked-in ROM was produced on 2026-07-14 with `/opt/wonderful` and:

| Package | Version |
| --- | --- |
| `target-wswan` | `0.1.0-3` |
| `target-wswan-examples` | `0.2.0.r44.811b739-1` |
| `target-wswan-syslibs` | `0.2.0.r254.d7d97ce-1` |
| `toolchain-gcc-ia16-elf-binutils` | `2.43.1.r119451.5cc0e071551-1` |
| `toolchain-gcc-ia16-elf-gcc` | `6.3.0.r147159.e7507d1845e-1` |
| `wf-tools` | `0.2.0-3` |

```sh
cd testroms/swan-song/wonderful_medium_sram
make clean all WONDERFUL_TOOLCHAIN=/opt/wonderful
```

- ROM size: 131,072 bytes
- ROM SHA-256: `ae3ea85cc6b5c3b32e1fac23d37dd4fce8ccb38ec2fcd80d4b80b868e59dc4b7`
- Local CRT SHA-256: `7a9111e8195d651c97b9b160b089fa2bcd093deac1819cf2dc5a547ad1d1af6d`
- `MEDIUM-SRAM OK` ROM offset: `0x1EDC3`
- `MEDIUM-SRAM FAIL` ROM offset: `0x1EDD2`
- Frame 0 raw RGB SHA-256: `479ee01521330c5d2aaf824e16c33e1b458f9640d23765973aac472bf4a0bfd7`
- Frame 1 raw RGB SHA-256: `3d4dc04e7d09202bd36b2401600bdb00c4489b89888bd7e4c52520a3e7e0c10b`

This is source/Verilator evidence. Pocket hardware behavior and persistent-save
lifecycle remain unverified.
