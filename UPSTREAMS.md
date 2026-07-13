# Upstream provenance

Pinned on 2026-07-12:

| Component | Repository | Commit | License |
| --- | --- | --- | --- |
| Pocket baseline | https://github.com/agg23/openfpga-wonderswan | `073213a2e5992cff23b174d17763cb6354ee862b` | Top-level file contains GPL v2 text; file notices vary |
| WonderSwan system reference | https://github.com/MiSTer-devel/WonderSwan_MiSTer | `8f7a4d670b4635eda0e518e7fd9a17ef8610db79` | `WonderSwan.sv` grants GPL v2-or-later; top-level file contains GPL v2 text; file notices vary |
| APF utility reference | https://github.com/agg23/analogue-pocket-utils | `78482d1b363606336f4535aa0adc2e957bc20558` | MIT |
| Official APF core template | https://github.com/open-fpga/core-template | `da3a021b1eaf742604d86d8dc9b33a6666263e6a` | Analogue APF notice; individual generated/vendor notices vary |
| Pocket NES Memories comparison | https://github.com/agg23/openfpga-nes (`savestates2`) | `c427ab08a91af43d2eab2073d0a7b1656972dd13` | Top-level file contains GPL v2 text; file notices vary |
| Pocket GB Memories comparison | https://github.com/budude2/openfpga-GBC (`Save-States`) | `0be702f55eb864b532835f30b11790e4ba61170d` | No top-level license file in the pinned tree; file notices vary |
| Pocket SNES video-mode comparison | https://github.com/agg23/openfpga-snes (`videomodes`) | `b8aa593f93b5df993a911302a74145e958eba553` | Top-level file contains GPL v2 text; file notices vary |
| openFPGA core inventory | https://github.com/openfpga-cores-inventory/analogue-pocket | `dfc9af340d4b2104bdc771831f7e08aa4df4e20f` | MIT |
| Pupdate distribution reference | https://github.com/mattpannella/pupdate | `07452a17af897d7c6d041fcc4dcad5100df67e48` | MIT |
| Official Chip32 assembler/image reference | https://github.com/open-fpga/bass-chip32 | `f3ad17dfd541e67b527298808ebef131e979ded4` / `v1.0.0` | MIT |
| Wonderful open test reference | https://github.com/asiekierka/ws-test-suite | `7dfa0e2e869d08386b685d6a56df0bcfaf181b47` | MIT |
| Wonderful native example reference | https://github.com/WonderfulToolchain/target-wswan-examples | `811b739ab1f0203336a08da8db34365d29869617` | CC0-1.0 example scaffold; linked libraries use zlib terms |
| Wonderful current system libraries | https://codeberg.org/WonderfulToolchain/target-wswan-syslibs | `d7d97ce9490c54aff3ad8ad5f4b60f1c547757ab` | zlib-style notices; component notices vary |
| Wonderful target documentation | https://github.com/WonderfulToolchain/wonderful-docs | `98dd8700b0f8ec71c6e05bcd11042956fdd6f230` | repository notice pages vary |
| Open WonderWitch OS / Misaki source mirror | https://github.com/OpenWitch/AthenaOS | `d37beae7482616313883dcfa4bdb7114d1ef5749` | AthenaOS MIT; bundled component/font notices vary; Misaki's official terms permit use/copy/distribution with or without modification and disclaim warranty |
| ares behavioral reference | https://github.com/ares-emulator/ares | `449b93716fb162632de2fd43bf2eba2064fa43f2` | ares core under ISC-style notice; bundled notices vary |
| Mesen behavioral reference | https://github.com/SourMesen/Mesen2 | `b9fa69ddc6d0a331fb103fdb5eef6904305703c2` | GPL v3 |

The repository history preserves Adam Gastineau's port commits. Robert Peip is
the original WonderSwan FPGA core author. The following findings come from the
checked-in history, not from repository-host license classification:

- A whitespace-insensitive comparison against the pinned official APF template
  finds `src/fpga/apf/apf_top.v` behaviorally identical. The project-specific
  `io_pad_controller.v` divergence clears every controller snapshot after a
  PAD timeout or reset so stale held inputs cannot survive link recovery.
- The pinned Pocket NES and GB save-state branches use the same small-FIFO
  controller family inherited by the WonderSwan port. They are useful protocol
  comparisons, but they do not establish that a 590,624-byte WonderSwan blob
  may be restored before the complete APF payload is staged and validated.
- The public openFPGA inventory still describes the 2023 WonderSwan 1.0.1
  release as supporting Memories. Swan Song deliberately reports Memories and
  sleep unsupported until complete-blob staging, fit/timing, and Pocket
  save/sleep/wake tests pass; future inventory metadata must match that state.

- MiSTer's first source-bearing commit (`2cebac3`, 2021-06-12) has a
  program-level notice in `WonderSwan.sv` granting GPL v2-or-later. The same
  commit contains `rtl/ddram.sv` and `rtl/sdram.sv`, which name Sorgelig and
  grant GPL v3-or-later. Its parent (`1cb59d6`) added the GPL v2 license text.
- Pocket's initial commit (`8aee749`, 2022-10-11) imported all 32 files under
  `src/fpga/core/rtl/` byte-for-byte from MiSTer commit `ccd8c2a`, the MiSTer
  head at that time. Pocket adapted MiSTer's `WonderSwan.sv` into
  `src/fpga/core/main.sv` (now `wonderswan.sv`) but omitted its copyright and
  GPL v2-or-later notice. Pocket added a byte-identical copy of MiSTer's GPL v2
  license text in `db389a8` on 2023-01-10; that commit did not add a project
  license declaration to the README or source files.
- The Pocket-specific loaders, FIFO, and I2S bridge carry MIT notices. APF and
  Intel-generated files retain their distinct vendor notices; the APF notice
  expressly says applicable MIT or GPL terms prevail over inconsistent APF
  terms.
- The new C++ simulation harness files `sim/verilator/sim_main.cpp`,
  `trace_logger.hpp`, and `trace_logger_test.cpp`, plus
  `sim/rtl/dpram_sim.vhd`, are marked GPL v2-only. The simulation source list
  does not include the GPL v3-or-later `ddram.sv` or `sdram.sv`, so that
  executable does not create the GPL-v2-only/GPL-v3 combination at issue.
  Other newly added build, test, and documentation files do not state a
  uniform project-wide license.

This history substantially narrows the apparent GPL version conflict. The
inherited WonderSwan program was expressly offered under GPL v2-or-later, not
GPL v2-only, so choosing GPL v3 for a combined work is compatible with the two
GPL v3-or-later memory-controller files. This follows the FSF's
[GPL version compatibility guidance](https://www.gnu.org/licenses/gpl-faq.en.html#v2v3Compatibility).
The current notices therefore do not show a direct GPL-v2-only/GPL-v3-only
contradiction in the inherited console core.

The audit does **not** establish release clearance for a new combined binary.
The Pocket adaptation removed the clearest program-level notice, many files
remain unheaded, and the top-level `LICENSE` is only a copy of the GPL v2 text.
The FSF advises that merely putting a GPL copy in a repository does not clearly
apply it to particular code
([guidance](https://www.gnu.org/licenses/gpl-faq.en.html#CopyingLicense)). The
tree also does not include the GPL v3 license text requested by the two explicit
GPL v3-or-later file notices. Before publishing a new bitstream, obtain a
maintainer/copyright-holder confirmation of the intended whole-project license,
restore or normalize notices with their approval, include every required
license text, and review the APF and Intel-generated-file terms. No inherited
notice has been changed by this audit.

The Pocket `core.json` declares `chip32.bin`, but the source checkout does not
carry that generated file. The official
[Chip32 documentation](https://www.analogue.co/developer/docs/chip32-vm)
identifies the custom Bass assembler, and the pinned
[open-fpga/bass-chip32 v1.0.0](https://github.com/open-fpga/bass-chip32/releases/tag/v1.0.0)
produces a 259-byte image from `src/support/chip32.asm`. Its SHA-256 is
`ca7a2b11c11250b4842c1853d6d500c0289e7065db479c11fde37c130440a81c`,
exactly matching the loader inside
[agg23's WonderSwan 1.0.1 release](https://github.com/agg23/openfpga-wonderswan/releases/tag/1.0.1).
The checked-in hexadecimal image preserves that exact output so packaging is
offline and host-independent; the build verifies both the assembly and decoded
image identities before including it.

The checked-in `testroms/` tree is byte-identical to the pinned MiSTer
`testroms/` directory. Those individual test files do not carry separate
license headers or declarations; their only repository-level license material
is MiSTer's top-level GPL v2 text, so their intended grant is not independently
stated. The directory contains no commercial game ROM.

The regression's bank and provenance probes are generated under `build/` and
are never checked in. They contribute new minimal 80186 programs and copy only
the final 16-byte reset-vector/header footer from the open `spritepriority.ws`
carrier above; the provenance probe changes the footer's color flag so the
color-only GDMA block can be exercised.

The deterministic input-replay regression likewise generates its 128 KiB mono
cartridge and controller schedule under `build/`. Its 80186 program, identity
marker, footer, checksum, and input text are repository-authored and contain no
third-party code, ROM, firmware, or game data. The keypad contract was reviewed
first against the current `joypad.vhd`, then the pinned ares [matrix
implementation](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cpu/keypad.cpp#L1-L38)
and WSdev's pinned [keypad register and physical
layout](https://ws.nesdev.org/w/index.php?title=Keypad&oldid=618). Those primary
sources corroborate that B5h bit 5 selects the horizontal X row and physical X2
appears in bit 1; no external source bytes are copied into the generated probe.

The mapper-memory and boot-overlay regressions are also generated under
`build/`, but are fully self-contained: they synthesize their own valid
cartridge footers/checksums and open simulation-only 4 KiB/8 KiB boot test
images. They include no console firmware or commercial data. The broad mapper
probe retains save type `0x03` (128 KiB SRAM) so its eight-space provenance
contract remains independent of the smaller-size correction. A dedicated pair
now differs only in save type `0x01` versus `0x02` and proves that both retain
distinct offsets `0x0000`, `0x2000`, and `0x7fff` before mirroring at `0x8000`.
That correction follows pinned [WSdev ROM-header revision
680](https://ws.nesdev.org/w/index.php?title=ROM_header&oldid=680), [Mesen2's
save-size table](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsConsole.cpp#L58-L65),
and [ares' loader](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/mia/medium/wonderswan.cpp#L85-L95),
which all map both header values to 32 KiB. No external source bytes are copied
into the generated pair.

The Sound-DMA regressions generate two self-contained 128 KiB Color cartridges
under `build/`; neither is checked in. The first minimal open 80186 program
streams four marker bytes from linear ROM. The second checks selected
source/length/control behavior in software and emits `PONSREATDHUZ` only after
its readback, terminal, pause/resume, live-edit, repeat, decrement, and held-zero
assertions pass. Both programs, sample bytes, identity markers, input text,
footers, and checksums are repository-authored and include no external carrier,
firmware, SDK, hardware-test binary, or commercial data.

A third Sound-DMA workload is checked in under
`testroms/ws-test-suite/sound_dma`: it is a byte-identical build of the pinned
MIT [ws-test-suite source](https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/src/color/dma/sound_dma/main.c)
with its exact source, configuration, MIT notice, linked Wonderful system-library
zlib notice, container digest, footer/checksum, and ROM/font hashes recorded in
the local README. It includes no BIOS, proprietary firmware, or commercial
game data. The pinned Wonderful build placed the source's `.sram` symbol in
segment zero, so the two SRAM-labeled tests produce 43 IRAM reads at
`0x0059..0x0068` and no cartridge-SRAM reads. The strict verifier makes that
limitation an acceptance condition rather than treating the green labels as
SRAM or wait-state evidence.

The contract was reviewed against pinned [WSdev DMA revision
562](https://ws.nesdev.org/w/index.php?title=DMA&oldid=562), [Mesen2's transfer
and control implementation](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsDmaController.cpp#L46-L192),
and ares' pinned [DMA](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/apu/dma.cpp#L1-L33)
and [I/O](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/apu/io.cpp#L160-L181)
paths. The sources diverge at two relevant edges: Mesen performs a held read
before substituting zero while ares skips the read, and Mesen rejects every
enable write at zero live length while ares assigns enable directly. The tests
therefore identify held reads as current translated policy and the all-write
zero rejection as Mesen/WSdev-consistent rather than claiming emulator or
hardware consensus. The inherited raw DMA-bus byte-enable also remains
distinct from logical SDMA sample width.

The Sound-DMA save-state contract was reviewed separately against pinned
[Mesen2 serialization](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsDmaController.cpp#L196-L213),
which preserves the live and reload counters, control-derived state,
frequency, and timer, and pinned ares [APU DMA
serialization](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/apu/serialization.cpp#L32-L44),
which preserves programmed and live source/length plus the DMA clock and
control fields. Both emulator models complete a transfer atomically inside
their host execution path, so neither has an FPGA shared-bus request or FSM
checkpoint to serialize. The new queued-request and granted-but-not-issued
read fields are therefore implementation-specific continuation state, not a
claim of emulator consensus.

The direct save/load regression is a repository-authored GHDL test bench and
contains no external ROM, firmware, or emulator code. It models the existing
state-bus capture/final-reset sequence and proves the unchanged legacy slot 17
alongside a versioned extension in the previously unused zero slot 18. Its
scope is exact nonzero timer-phase restoration, divergent live/reload counters
through a terminal repeat, pending-IDLE and enabled/disabled pre-bus
single-read continuation, legacy all-zero fallback, invalid-header fallback,
and impossible-state sanitization. These are translated-RTL continuation
claims at the direct bench's tested state-bus boundaries; they do not establish
arbitrary mid-transaction, external save-format, physical timing, or Pocket
hardware equivalence.

The paired planar/packed 4bpp regressions likewise generate self-contained
128 KiB Color cartridges under `build/`. Their 80186 programs, pixel patterns,
palettes, markers, footers, and checksums are repository-authored; they use no
carrier ROM, SDK, assembler, firmware, font, or third-party asset. Their mode,
tile, screen-entry, palette, and footer contracts were reviewed in the brief's
source order: first the current `gpu.vhd`/`gpu_bg.vhd` mode, address, and decode
paths; then pinned ares
[screen attributes](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/screen.cpp#L12-L27)
and [planar/packed fetches](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/memory.cpp#L15-L43);
then Mednafen 1.32.1+dfsg-3's pinned
[planar/packed tile decode](https://sources.debian.org/src/mednafen/1.32.1%2Bdfsg-3/src/wswan/tcache.cpp/#L97-L168);
then WSdev's pinned [SoC mode bits](https://ws.nesdev.org/w/index.php?title=SoC&oldid=641),
[tile data](https://ws.nesdev.org/w/index.php?title=Display/Tile_Data&oldid=504),
[screen entries](https://ws.nesdev.org/w/index.php?title=Display/Screens&oldid=506),
and [palette layout](https://ws.nesdev.org/w/index.php?title=Display/Palette&oldid=514),
plus the current [ROM-header](https://ws.nesdev.org/wiki/ROM_header) page. No
external source or WSdev content is copied into the generated images.

The Color sprite-priority regression also generates a self-contained 128 KiB
cartridge under `build/`; its raw 80186 program, transparent/solid tiles,
palettes, descriptors, marker, footer, and checksum are repository-authored.
The priority contract was reviewed first against the current `gpu.vhd` and
`sprites.vhd`; then pinned ares [sprite selection and
attributes](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/sprite.cpp#L39-L63)
and [composition](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/dac.cpp#L1-L33);
then Mednafen 1.32.1+dfsg-3's pinned [sprite
composition](https://sources.debian.org/src/mednafen/1.32.1%2Bdfsg-3/src/wswan/gfx.cpp/#L784-L904);
then WSdev's pinned [sprite attributes and list
order](https://ws.nesdev.org/w/index.php?title=Display/Sprites&oldid=507) and
[layer order](https://ws.nesdev.org/w/index.php?title=Display&oldid=555); then
the pinned MIT ws-test-suite [sprite scanline/list-order hardware
test](https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/src/mono/display/sprite_scanline_limit/main.c#L8-L82).
That open hardware test corroborates ordinary list ordering and the 32-sprite
limit; it does not exercise the critical Color fallback, for which no directly
applicable reported real-hardware result was found. Acceptance is therefore
limited to translated RTL against the pinned reference contract. No external
code, ROM, firmware, graphics, or palette data is copied into the probe.

The checked-in `tile_screen_extended_range.wsc` fixture is a byte-identical
build of the pinned MIT ws-test-suite source. Its local README records the
pinned Wonderful container, ROM hash, source files, and linked
`target-wswan-syslibs` zlib notice. It is open test software and includes no
firmware or commercial game content. The v6 atomic sprite-row contract was
reviewed first against the current `gpu.vhd`/`sprites.vhd` handoff, then pinned
ares [OAM synchronization and scanline decode](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/sprite.cpp#L1-L63),
Mednafen's [sprite composition](https://sources.debian.org/src/mednafen/1.32.1%2Bdfsg-3/src/wswan/gfx.cpp/#L784-L904),
WSdev's pinned [sprite format](https://ws.nesdev.org/w/index.php?title=Display/Sprites&oldid=507),
and that fixture's pinned [source](https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/src/color/display/tile_screen_extended_range/main.c#L8-L134).
Those sources validate attributes, scanline selection, and open stimulus; none
reports this translated RTL's internal line-buffer acceptance edge, so the
atomic provenance claim is explicitly simulation-only.

The checked-in `80186_quirks.ws` fixture is likewise a byte-identical build of
the pinned MIT ws-test-suite source at `7dfa0e2e`. Its local README records the
pinned Wonderful container, `target-wswan-syslibs` version and zlib notice,
source files, 131,072-byte size, and ROM SHA-256
`b44090665f0165c7e3279da13359a0b27c69e3127823d55b2bb16f3dd4a2eb1c`.
The upstream-authored [test vectors](https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/src/mono/cpu/80186_quirks/tests.s#L10-L39)
establish D4/AAM and D5/AAD base-16 results plus D6/SALC values for both carry
states. They do not test flags, D4 base-zero, memory side effects, or timing.
Renesas's official [V30MZ hardware manual](https://www.renesas.com/en/document/lbr/v30mztm-hardware-preliminary)
lists CVTBD/AAM at 17 clocks and CVTDB/AAD at six, while the official
[16-Bit V Series instruction manual](https://www.renesas.com/en/document/mah/16-bit-v-seriestm-instruction)
marks AAM parity/sign/zero as result-defined and auxiliary-carry/carry/overflow
as undefined. The shared-RTL correction was also reviewed against pinned ares
[adjust instructions](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/component/processor/v30mz/instructions-adjust.cpp#L48-L63)
and [SALC](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/component/processor/v30mz/instructions-misc.cpp#L71-L78),
plus pinned Mesen's [AAM/AAD](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsCpu.cpp#L729-L767)
and [SALC](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsCpu.cpp#L595-L599).
Both references agree on D5's full eight-bit ADD flags and D6's eight-clock,
flag-preserving, memory-free behavior. They diverge on AAM flags, but pinned
Mesen and the documented result semantics agree that the three defined flags
derive from AL; the core preserves the undefined flags. The
imported MiSTer timing ROM's D6 `XLAT` label is not
used as an opcode oracle; its measured timing expectation nevertheless agrees
with the independent eight-clock SALC references. These are translated-model
and reference-correlated claims, not Pocket hardware validation.

The complementary CPU-quirks probe is generated under `build/` and is never
checked in. Its 128 KiB mono image, machine code, interrupt handler, identity
marker, footer, and checksum are repository-authored; it uses no carrier ROM,
assembler, SDK, firmware, or third-party binary. Its exact-result contract
extends the open fixture with defined AAM flags, the full AAD byte-ADD flag
model shared by the pinned references, AAM base-zero vector-0 state and return
IP, full before/after SALC PUSHF words, and complete-history exclusion of a
SALC data read. The verifier permits only ROM-byte-matched instruction prefetches during
the observed SALC intervals. Because the inherited CPU subtracts prefetch
buffer credit from its delay counter, those end-to-end trace intervals are
reported only as observer deltas; the eight-clock SALC value remains a pinned
reference contract, not a physical timing result.

The opt-in trace/frame manifest v2 binds the simulator's raw RGB artifacts to
the exact reset-relative system cycles on which their final visible pixels are
published. Its terminology is intentionally narrower than a hardware frame:
WSdev's pinned [timing revision](https://ws.nesdev.org/w/index.php?title=Timing&oldid=645)
documents 224 visible pixels across 144 of 159 default lines and 256 display
clocks per line, while the pinned [LCD register
research](https://ws.nesdev.org/w/index.php?title=Display/IO_Ports&oldid=582)
documents a programmable final line. Pinned ares independently ends a hardware
frame when `vcounter` reaches `max(144, vtotal + 1)`
([PPU implementation](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/ppu.cpp#L188-L228)).
The manifest therefore certifies artifact publication, path, size, and content;
it does not relabel that host observation as VBlank or infer that every trace
event in the preceding interval causally contributed a visible pixel.

The screen-authenticity path was reviewed in the brief's required order. The
inherited Pocket/pinned MiSTer baseline exposes native RGB444 and only finite
equal-weight blend formulas. Pinned ares supplies the optional
[Color/SwanCrystal matrix](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/color.cpp#L1-L29)
and enables its generic recursive
[interframe average](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/node/video/screen.cpp#L251-L266).
The official
[Mednafen 1.32.1 source archive](https://mednafen.github.io/releases/),
SHA-256 `de7eb94ab66212ae7758376524368a8ab208234b33796625ca630547dbc83832`,
was downloaded under untracked `build/research/` and its
`src/wswan/gfx.cpp::WSwan_SetPixelFormat()` maps every channel by exactly
`nibble * 17`; no WonderSwan temporal filter or alternate panel matrix was
found there. WSdev's pinned
[palette research](https://ws.nesdev.org/w/index.php?title=Display/Palette&oldid=514)
states that the models have no canonical shared palette and identifies their
panel families, but publishes no WonderSwan Color or SwanCrystal temporal
constants. Analogue's official
[`video.json` contract](https://www.analogue.co/developer/docs/core-definition-files/video-json)
recommends generic LCD modes and likewise defines no WonderSwan-specific
profile. Consequently raw x17 remains default, the exact ares matrix is
explicitly optional, and the 50/25/25 response is documented as a
project-designed finite approximation of ares' recursive weights rather than
measured panel behavior. No Mednafen, ares, WSdev, or Analogue source bytes are
copied into the RTL or tests; formulas are independently expressed and
exhaustively checked in `sim/rtl/apf_temporal_blend_tb.sv`.

The checked-in `sjis_glyph_provenance.wsc` fixture is a reproducible native
Wonderful build of project source plus six unmodified 8×8 rows from Misaki
Gothic. Its local README pins the author's official PNG and BDF archives and
hashes, a byte-identical Git mirror/commit, the source PNG/hash, exact Unicode
and Shift-JIS manifest, Wonderful container and package versions, ROM hash,
and full trace/pixel acceptance checks. The Misaki author grants unlimited use,
copy, and distribution, modified or unmodified, commercially or otherwise;
the notice is copied beside the fixture. No BIOS, WonderWitch image, or
commercial game data is included.
