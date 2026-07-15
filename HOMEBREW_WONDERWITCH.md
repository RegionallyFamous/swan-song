# Developing homebrew for Swan Song

This is the source/simulation support boundary for homebrew built with the
[Wonderful Toolchain](https://wonderful.asie.pl/docs/target/wswan/). It does not
claim Quartus timing closure or Analogue Pocket hardware validation. Swan Song
does not include or download a WonderSwan BIOS, WonderWitch firmware, or any
commercial image.

## Recommended cartridge target

Start from Wonderful's current `wswan/medium` template and emit a `.ws` or
`.wsc` ROM between 64 KiB and 16 MiB in whole 64 KiB banks. Power-of-two files
use the unchanged direct-load path. A compact non-power-of-two file must have a
valid final 16-byte WonderSwan footer/checksum; Swan Song fills the lower mapper
prefix with `0xff` and right-aligns it in the next-power-of-two aperture, as
documented by [WSdev](https://ws.nesdev.org/wiki/ROM_header). The medium model uses far code
pointers and permits code beyond one 64 KiB segment. Ordinary data pointers
remain near and point into RAM; declare immutable ROM data with `__wf_rom` and
use far-aware APIs where appropriate. The core's current Pocket package still
requires the user to supply both `bw.rom` and `color.rom` even for a cartridge
that only uses one model.

Current Wonderful has a known gcc-ia16 problem when calling through an array of
far function pointers at `-O1` or higher. Follow the official workaround and
compile the affected caller with `__attribute__((optimize("-O0")))`. Also note
that `-fno-function-sections` can reduce medium-model alignment/call overhead;
measure before changing it globally.

The checked-in
[`wonderful_medium_sram`](testroms/swan-song/wonderful_medium_sram/README.md)
fixture adds deterministic coverage for the advanced `wswan/medium-sram`
target. It was built with current `target-wswan-syslibs` commit
[`d7d97ce`](https://codeberg.org/WonderfulToolchain/target-wswan-syslibs/commit/d7d97ce9490c54aff3ad8ad5f4b60f1c547757ab)
and the example scaffold at
[`811b739`](https://github.com/WonderfulToolchain/target-wswan-examples/tree/811b739ab1f0203336a08da8db34365d29869617).
In Verilator it proves:

- the fixture's pinned, zlib-derived CRT requires physical Color hardware,
  enables System Control 2 bit 7 before selecting its high stack, selects
  DS=`1000h`, clears `.bss` in cartridge SRAM, and copies initialized `.data`
  there from ROM;
- medium-model CRT code far-jumps into `main` and calls current console
  libraries across segments;
- far ROM strings remain in the cartridge image;
- exact SRAM reads return `0x5AA5`/zero after CRT setup and `0xA55A`/`0xC33C`
  after program writes; and
- the successful branch renders `MEDIUM-SRAM OK` and reaches HLT in two frames.

`medium-sram` needs deliberate startup and memory planning:

- With Wonderful 0.2.0 and `SRAM_32KB`, `__wf_heap_top` is `8000h` and SS
  remains console IRAM. The stock
  [`crt0.s`](https://codeberg.org/WonderfulToolchain/target-wswan-syslibs/src/commit/d7d97ce9490c54aff3ad8ad5f4b60f1c547757ab/crts/src/crt0.s)
  clears `$60.7` before its first push, while [WSdev documents that bit as the
  gate for extra RAM and DMA](https://ws.nesdev.org/w/index.php?title=SoC&oldid=641).
  A normal call at the start of `main` is too late because CRT and function
  prologues already use the stack. The regression therefore links a pinned,
  explicitly altered CRT that checks physical Color hardware and enables
  `$60.7` before selecting SP=`8000h`. This is a homebrew startup workaround,
  not a reason for an emulator or FPGA core to expose Color RAM while the bit
  is clear.
- Capping the pre-main stack at `4000h` was tested and rejected. It removed
  unmapped accesses, but the stack collided with the console/font workspace
  and `wsx_console_init_default` never returned. Preserve the normal high
  stack and enable Color RAM in startup code before any stack operation.
- Wonderful names header value `01h` `SRAM_8KB`; current WSdev/emulator research
  and Swan Song treat both `01h` and `02h` as 32 KiB. Prefer Wonderful's
  `SRAM_32KB`/type `02h` spelling for an unambiguous current project.
- The CRT rewrites initialized and zeroed C sections on every boot. Do not
  overlap those sections with persistent game records. Either treat this
  target's SRAM data segment as volatile workspace or reserve a non-overlapping
  persistent region with an audited section/link layout.

## Core-specific checklist

- Set `color = true` for Color-only code and use `.wsc`; Auto model follows the
  cartridge footer. A filename extension is not a model override.
- Use a supported SRAM/EEPROM footer type. Swan Song currently allocates
  32/128/256/512 KiB for SRAM `01/02`/`03`/`04`/`05`, and 128/2048/1024 bytes
  for EEPROM `10`/`20`/`50`; RTC adds a 12-byte Pocket save trailer.
- Keep mapper assumptions explicit. Bandai 2001 C0-C3 banking is covered. For
  canonical footer RTC value `01h` (used as the Bandai 2003 selector), the
  `CFh`, `D0h`, `D2h`, and `D4h` low-byte aliases resolve through the same bank
  registers. `D1h`, `D3h`, and `D5h` implement the documented two high bits,
  zero upper readback, mapper gating, reset, and save-state replay. The core
  still accepts at most 16 MiB, so those latches do not grant access to the
  2003 mapper's wider ROM range.
- Do not target PocketChallenge v2 (`.pc2`). Its pinstrap boot, keypad matrix,
  absent internal EEPROM, and asset path are not implemented.
- Test both orientations and the real keypad matrix. Pocket display forcing
  rotates presentation only; the running program's orientation signal selects
  the game-visible X/Y cluster mapping.
- Treat Memories/Sleep as unavailable until the production full-state backend
  and hardware lifecycle pass their release gates.

Run the complete source/simulator gate with `make regression`. The narrow
medium-SRAM command is recorded in the fixture README and intentionally uses
only an open ROM plus the simulator's generated open boot image.

## WonderWitch boundary

Wonderful's `wwitch` target remains less mature than native `wswan`. It emits a
traditional `.fx` application and current Wonderful can also assemble that
application into a self-contained `.ws` with `wf-wwitchtool mkrom`. The target
assumes DS points to SRAM at `1000h`, SS points to console IRAM, and system
services are supplied by a Freya-compatible BIOS/OS. WSdev documents FreyaBIOS
in the final 64 KiB of a WonderWitch cartridge and FreyaOS in the preceding
64 KiB; FreyaOS owns the filesystem and launches `.fx` programs:

- [Wonderful WonderWitch target notes](https://wonderful.asie.pl/docs/target/wswan/#wonderwitch)
- [FreyaBIOS](https://ws.nesdev.org/wiki/WonderWitch/FreyaBIOS)
- [FreyaOS and `.fx` format](https://ws.nesdev.org/wiki/WonderWitch/FreyaOS)
- [FreyaOS filesystem](https://ws.nesdev.org/wiki/WonderWitch/Filesystem)
- [WonderWitch memory map](https://ws.nesdev.org/wiki/WonderWitch/Memory_map)

The current
[Wonderful WonderWitch guide](https://wonderful.asie.pl/wiki/doku.php?id=wswan%3Aguide%3Awwitch)
documents `mkrom` as the emulator/flash-cartridge path. Its required clean-room
firmware comes from the separately installed `target-wswan-athenaos` package,
not from a standard WonderSwan BIOS. OpenWitch's
[AthenaOS](https://github.com/OpenWitch/AthenaOS/tree/d37beae7482616313883dcfa4bdb7114d1ef5749)
is the open Freya-compatible implementation behind that package. Swan Song
does not check in the generated firmware or composite ROM.

Swan Song now makes one narrow WonderWitch claim: the pinned Wonderful hello
fixture, wrapped as a read-only AthenaOS `mkrom` image, boots and executes BIOS
text/input services in the translated system model. See
[`WONDERWITCH_VALIDATION.md`](WONDERWITCH_VALIDATION.md). The remaining boundary
is explicit:

- APF launches the generated `.ws`; it does not expose standalone `.fx` files
  or a host-managed Freya filesystem;
- the exact Bandai 2003 selector implements port `CEh` bit 0 and its byte-wide
  volatile ROM/flash window, but not the MBM29DL400TC unlock/program/erase
  command state or APF persistence documented by
  [WSdev](https://ws.nesdev.org/wiki/WonderWitch/Flash); and
- the generated image has not been run on Pocket hardware, and writable
  WonderWitch software remains unverified.

The mapper audit is intentionally narrower than an emulator feature list:

| Cartridge interface | Current status | Evidence boundary |
| --- | --- | --- |
| Bandai 2001 C0-C3 banks | Implemented | Generated 2 MiB runtime mapper traces |
| Bandai 2001 external EEPROM | Implemented | Controller/backing simulation and Pocket save contracts |
| Bandai 2003 RTC | Implemented | Deterministic RTC/save regressions; Pocket timing remains hardware-gated |
| Bandai 2003 CF/D0/D2/D4 low aliases | Implemented for canonical footer RTC/2003 selector `01h` | Black-box VHDL readback plus resolved ROM/RAM offsets |
| Bandai 2003 D1/D3/D5 high bank bytes | Register semantics implemented for canonical selector `01h`; storage above 16 MiB is not | Exhaustive black-box byte writes, mapper/reset gating, upper-bit masking, and unchanged save-image replay; wider addressing requires a coordinated SDRAM/APF layout change |
| Bandai 2003 CE self-flash window | Volatile routing implemented for canonical selector `01h` | Black-box reset/readback, mapper rejection, ROM/SRAM masks, even/odd byte lanes, ordinary ROM write protection, and `cart_flash` trace labeling |
| MBM29DL400 command state and persistence | Not implemented | Unlock/program/erase semantics plus a title-bound APF backing file are required before a writable WonderWitch cartridge claim |
| Bandai 2003 GPO | Four-bit `CCh` direction and `CDh` data register semantics implemented for canonical selector `01h` | Exhaustive black-box masking, mapper/reset isolation, and register-image replay; no Pocket-side cartridge peripheral is attached, so this is not an external-pin/device claim |
| KARNAK / PocketChallenge v2 timer, ADPCM, IRQ, boot mode | Not implemented | Separate machine/peripheral target, not a `.pc2` filename alias |

This ordering follows the current public hardware documentation: the common
[mapper](https://ws.nesdev.org/wiki/Mapper) defines C0-C3; the
[Bandai 2003](https://ws.nesdev.org/wiki/Bandai_2003) page defines the aliases,
wider banks, GPO, RTC, and CE window; the
[WonderWitch flash](https://ws.nesdev.org/wiki/WonderWitch/Flash) page binds CE
to the MBM29DL400TC; and [KARNAK](https://ws.nesdev.org/wiki/KARNAK) adds the
PocketChallenge-specific timer/ADPCM path. Current ares independently models
the same split in its pinned
[I/O mapper](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cartridge/io.cpp),
[memory mapper](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cartridge/memory.cpp),
[all-ones bank reset state](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cartridge/cartridge.hpp#L149-L156),
and [WonderWitch detector](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/mia/medium/wonderswan.cpp).

The first responsible milestone is complete: a pinned AthenaOS package, a
deterministic filesystem containing an open `.fx`, and bound boot, launch,
BIOS-call, CPU, and visible-output evidence. The mapper-facing `CEh` routing
milestone is also complete, but deliberately does not treat raw SDRAM writes as
a real flash chip. The next milestone is MBM29DL400 unlock/program/erase state,
followed by title-bound filesystem persistence in simulation and both read-only
and writable Pocket cases before expanding the compatibility claim.

## Research pins

- Wonderful docs repository:
  [`98dd870`](https://github.com/WonderfulToolchain/wonderful-docs/tree/98dd8700b0f8ec71c6e05bcd11042956fdd6f230)
- Wonderful system libraries:
  [`d7d97ce`](https://codeberg.org/WonderfulToolchain/target-wswan-syslibs/commit/d7d97ce9490c54aff3ad8ad5f4b60f1c547757ab)
- Wonderful examples:
  [`811b739`](https://github.com/WonderfulToolchain/target-wswan-examples/tree/811b739ab1f0203336a08da8db34365d29869617)
- Open AthenaOS:
  [`d37beae`](https://github.com/OpenWitch/AthenaOS/tree/d37beae7482616313883dcfa4bdb7114d1ef5749)
- Current WonderWitch development guide, including `mkrom`, reviewed at its
  2026-01-08 revision:
  [Wonderful Wiki](https://wonderful.asie.pl/wiki/doku.php?id=wswan%3Aguide%3Awwitch)
- WSdev pages were reviewed at FreyaBIOS revision 699, FreyaOS revision 676,
  filesystem revision 593, and flash revision 482.
- Pinned MiSTer system reference:
  [`8f7a4d6`](https://github.com/MiSTer-devel/WonderSwan_MiSTer/tree/8f7a4d670b4635eda0e518e7fd9a17ef8610db79).
  Its post-2021 WonderSwan changes do not add a newer system-logic compatibility
  path beyond the established PocketChallenge-v2/palette/IDIV/window work, so
  this Phase 6 result is a toolchain/runtime validation, not an imported RTL fix.
