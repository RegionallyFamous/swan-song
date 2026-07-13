# Wonderful medium-SRAM fixture

This open WonderSwan Color ROM exercises a modern Wonderful configuration that
the prior Swan Song fixtures did not: `wswan/medium-sram` with a 32 KiB
cartridge-SRAM data segment. It verifies the current CRT's ROM-to-SRAM `.data`
copy, SRAM `.bss` clear, far-code entry into `main`, far ROM strings, current
`libws`/`libwse`/`libwsx` console setup, and read/write access through DS=`1000h`.

The source starts with `initialized_word = 0x5AA5` and an uninitialized
`zero_word`. `main` requires the CRT-provided values, changes them to `0xA55A`
and `0xC33C`, reads both back, and renders `MEDIUM-SRAM OK` only if all four
checks pass. The regression binds the exact ten SRAM events, successful branch,
terminal HLT, 14 map cells, and final raster.

The Color header is intentional. With `SRAM_32KB`, Wonderful 0.2.0's
`medium-sram` linker places `__wf_heap_top` at `8000h`; the CRT uses that as SP
while SS remains console IRAM. `8000h` is valid on WonderSwan Color's 64 KiB
IRAM but outside a mono WonderSwan's 16 KiB IRAM. See
[`HOMEBREW_WONDERWITCH.md`](../../../HOMEBREW_WONDERWITCH.md).

## Provenance and rebuild

The build skeleton and console setup are adapted from the CC0
[Wonderful examples](https://github.com/WonderfulToolchain/target-wswan-examples)
at commit `811b739ab1f0203336a08da8db34365d29869617`. The linked runtime is from
[target-wswan-syslibs](https://codeberg.org/WonderfulToolchain/target-wswan-syslibs)
at commit `d7d97ce9490c54aff3ad8ad5f4b60f1c547757ab` and is covered by the adjacent
zlib notice. The probe changes and verifier are Swan Song project work under
the fixture's CC0 terms; no BIOS, WonderWitch firmware, or commercial data is
present.

The checked-in ROM was produced on 2026-07-13 with `/opt/wonderful` and:

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
- ROM SHA-256: `b7f6a4e1e3a73eb4fa615a73f5e9a4cbb8c46a6b5157ade4e1d814c30da034aa`
- `MEDIUM-SRAM OK` ROM offset: `0x1EE05`
- `MEDIUM-SRAM FAIL` ROM offset: `0x1EE14`
- Frame 0 raw RGB SHA-256: `b404fb94d84fa4bd527d8eabaf2d13393f5c43f03d838c4aa2a8c95855aef511`
- Frame 1 raw RGB SHA-256: `3d4dc04e7d09202bd36b2401600bdb00c4489b89888bd7e4c52520a3e7e0c10b`

This is source/Verilator evidence. Pocket hardware behavior and persistent-save
lifecycle remain unverified.
