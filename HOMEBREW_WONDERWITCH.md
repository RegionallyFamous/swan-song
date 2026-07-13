# Developing homebrew for Swan Song

This is the source/simulation support boundary for homebrew built with the
[Wonderful Toolchain](https://wonderful.asie.pl/docs/target/wswan/). It does not
claim Quartus timing closure or Analogue Pocket hardware validation. Swan Song
does not include or download a WonderSwan BIOS, WonderWitch firmware, or any
commercial image.

## Recommended cartridge target

Start from Wonderful's current `wswan/medium` template and emit a power-of-two
`.ws` or `.wsc` ROM between 64 KiB and 16 MiB. The medium model uses far code
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

- the CRT selects DS=`1000h`, clears `.bss` in cartridge SRAM, and copies
  initialized `.data` there from ROM;
- medium-model CRT code far-jumps into `main` and calls current console
  libraries across segments;
- far ROM strings remain in the cartridge image;
- exact SRAM reads return `0x5AA5`/zero after CRT setup and `0xA55A`/`0xC33C`
  after program writes; and
- the successful branch renders `MEDIUM-SRAM OK` and reaches HLT in two frames.

`medium-sram` needs deliberate memory planning:

- With Wonderful 0.2.0 and `SRAM_32KB`, `__wf_heap_top` is `8000h` and the CRT
  uses that as SP while SS remains console IRAM. Use a Color cartridge/model,
  whose 64 KiB IRAM contains that address. The same build with a mono header
  falls outside the original WonderSwan's 16 KiB IRAM and did not reach `main`
  in simulation.
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
- Keep mapper assumptions explicit. The regular 2001/2003 paths are covered;
  the core accepts at most 16 MiB even though the later mapper exposes a wider
  theoretical bank range.
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

Wonderful's `wwitch` target is experimental and produces an `.fx` application,
not a self-contained cartridge ROM. The target assumes DS points to SRAM at
`1000h`, SS points to console IRAM, and system services are supplied by
FreyaBIOS/FreyaOS. WSdev documents FreyaBIOS in the final 64 KiB of a
WonderWitch cartridge and FreyaOS in the preceding 64 KiB; FreyaOS owns the
filesystem and launches `.fx` programs:

- [Wonderful WonderWitch target notes](https://wonderful.asie.pl/docs/target/wswan/#wonderwitch)
- [FreyaBIOS](https://ws.nesdev.org/wiki/WonderWitch/FreyaBIOS)
- [FreyaOS and `.fx` format](https://ws.nesdev.org/wiki/WonderWitch/FreyaOS)
- [FreyaOS filesystem](https://ws.nesdev.org/wiki/WonderWitch/Filesystem)
- [WonderWitch memory map](https://ws.nesdev.org/wiki/WonderWitch/Memory_map)

The current Wonderful template successfully compiles to `.fx`, but its ROM
assembly tool requires an installed OS/BIOS package. That dependency is the
environment, not something Swan Song may silently replace with a standard
WonderSwan BIOS. OpenWitch's
[AthenaOS](https://github.com/OpenWitch/AthenaOS/tree/d37beae7482616313883dcfa4bdb7114d1ef5749)
is an open Freya-compatible implementation and is the appropriate future test
source, but no Athena/Freya image is bundled here.

Swan Song does **not** currently claim WonderWitch compatibility:

- APF exposes `.ws`/`.wsc` cartridge assets, not standalone `.fx` files or a
  host-managed Freya filesystem;
- the inherited mapper has no implementation of WonderWitch's MBM29DL400TC
  flash command state or the Bandai 2003 port-`CEh` write window documented by
  [WSdev](https://ws.nesdev.org/wiki/WonderWitch/Flash); and
- no complete, redistributable AthenaOS cartridge image has been run through
  this simulator or on Pocket hardware.

A responsible WonderWitch milestone is therefore: build a pinned AthenaOS
image locally from source, create a deterministic filesystem containing a
small open `.fx`, implement/verify the required port-`CEh` flash behavior if
the workload exercises it, and bind boot, launch, filesystem, visible output,
and persistence in simulation before enabling any Pocket file extension or
making a compatibility claim.

## Research pins

- Wonderful docs repository:
  [`98dd870`](https://github.com/WonderfulToolchain/wonderful-docs/tree/98dd8700b0f8ec71c6e05bcd11042956fdd6f230)
- Wonderful system libraries:
  [`d7d97ce`](https://codeberg.org/WonderfulToolchain/target-wswan-syslibs/commit/d7d97ce9490c54aff3ad8ad5f4b60f1c547757ab)
- Wonderful examples:
  [`811b739`](https://github.com/WonderfulToolchain/target-wswan-examples/tree/811b739ab1f0203336a08da8db34365d29869617)
- Open AthenaOS:
  [`d37beae`](https://github.com/OpenWitch/AthenaOS/tree/d37beae7482616313883dcfa4bdb7114d1ef5749)
- WSdev pages were reviewed at FreyaBIOS revision 699, FreyaOS revision 676,
  filesystem revision 593, and flash revision 482.
- Pinned MiSTer system reference:
  [`8f7a4d6`](https://github.com/MiSTer-devel/WonderSwan_MiSTer/tree/8f7a4d670b4635eda0e518e7fd9a17ef8610db79).
  Its post-2021 WonderSwan changes do not add a newer system-logic compatibility
  path beyond the established PocketChallenge-v2/palette/IDIV/window work, so
  this Phase 6 result is a toolchain/runtime validation, not an imported RTL fix.
