# Roadmap status

## Phase 0 — faithful rebuild

| Item | Status | Evidence |
| --- | --- | --- |
| History-preserving Pocket fork | Complete | current branch is based at Pocket `1.0.1` / `073213a2` and retains its ancestry |
| Upstream pins and license audit | Provenance complete; release clearance open | `UPSTREAMS.md`; MiSTer program notice is GPL v2-or-later and is version-compatible with GPL-v3-or-later RTL, but Pocket omitted that notice and the tree lacks a GPL v3 license copy |
| Architecture and port boundary | Complete | `ARCHITECTURE.md`, `PORTING.md` |
| System simulation | Implemented for open tests | deterministic GPU-framebuffer hashes for two checked-in MiSTer tests, Wonderful's WSC extended-range fixture, and the native Shift-JIS/Misaki glyph fixture via `make regression`, plus a pinned Wonderful `initfini` pass recorded in `WONDERFUL_VALIDATION.md`; Pocket wrappers and SDRAM controller are outside this harness |
| PNG framebuffer output | Complete | `sim/verilator/rgb_to_png.py` |
| Optional waveform trace | Complete at whole-design VCD level | `--trace FILE.vcd` |
| Structured event trace | V5 runtime verified in Verilator | simulation-gated CPU, bank-register, completion-aligned display word/collision, completed CPU/GDMA/SDMA memory, and atomic Screen 1/2 background-cell taps; v5 CSV/JSONL with v1-v5 CSV fixtures; translated open-ROM regression plus focused atomic decode/grouping/writer-snapshot tests pass; `sim/verilator/TRACE.md` |
| Quartus bitstream | Blocked on host tool availability | requires supported Linux/Windows Quartus 21.1.1 host |
| Timing closure | Not tested | requires Quartus build |
| Hardware equivalence | Not tested | requires user-approved Pocket validation |

Phase 0 is not complete as a hardware deliverable until Quartus compilation,
timing closure, and on-device Pocket testing are performed.

## Phase 1 — debug instrumentation

| Item | Status | Evidence needed or available |
| --- | --- | --- |
| ROM bank-switch writes | Verified with generated open probe | `make regression` executes distinct byte writes to C0-C3 plus a word write spanning C0-C1, and requires their exact accepted sequence, nonzero instruction IDs, and origin PCs (`0xf0003`, `0xf0007`, `0xf000b`, `0xf000f`, `0xf0014`); both bytes of the word write share one instruction identity; no probe binary is checked in |
| VRAM/character fetch addresses | Raw and atomic runtime paths verified | open-ROM regression requires all six Screen 1/2 map/tile and sprite table/tile roles with aligned completion data and collision status; v5 binds a promoted background map word to decoded tile attributes and its contributing row; the open Shift-JIS fixture binds six licensed Misaki characters to exact ROM offsets, GDMA tile writers, CPU map writers, 96 promoted rows, and final pixels; title-specific glyph provenance remains open |
| CPU PC ranges | Verified with running ROMs | regression checks `CS:IP` against wrapped physical PC and disjoint range-union containment; Wonderful execution terminates at the expected `0xff68b` loop |
| Memory provenance | All eight trace-space labels runtime verified with generated open probes | paired complete-from-reset traces require 36,817 memory plus five bank events each and exact `iram`, `cart_sram`/`absent_sram`, `cart_rom0`, `cart_rom1`, `cart_rom_linear`, `boot_rom`, and mono `unmapped` behavior; checks bind ROM/boot inputs, values, masks, offsets, CPU origins, ROM aliases, and the separate GDMA chains |
| Sound-DMA provenance | Runtime verified with generated open WSC probe | the `sdma` filter returns exactly four one-shot linear-ROM reads at `0xf0100..0xf0103`, with exact returned words, mapped offsets, no CPU origin, and 1,536 trace-clock/128 CPU-clock cadence; raw inherited `byte_enable=3` is recorded without treating it as the one-byte sample width |
| Boot-ROM overlay and lockout | Runtime verified for mono and Color models | generated 4 KiB/8 KiB open test images execute from byte zero, read exact markers at `0xff100`/`0xfe100`, write A0 lockout, then require physical addresses `0xffff0..0xffffe` to change from mono boot offsets `0xff0..0xffe` or Color offsets `0x1ff0..0x1ffe` to cartridge offsets `0x1fff0..0x1fffe`; no proprietary firmware is used |
| Display-to-writer correlation | Verified on open regression | complete-from-reset manifest plus byte-lane IRAM scoreboard matches all 78,940 physical fetches: 78,750 exact CPU writers, 190 defined power-up prefetches, zero mismatches/collisions; `correlate_provenance.py` |
| Atomic background-cell correlation | Verified on open regression | `correlate_bg_cells.py` independently groups Screen 1/2 map/tile reads, validates 2bpp selected-word and 4bpp two-word rows, and snapshots byte writers/GDMA sources at the raw-fetch edge; regression validates 26,224 bootstrap cells, 5,176 extended-range Color cells, and 8,307 Shift-JIS fixture cells, with no atomic mismatch/collision |
| Open Japanese text workload | Verified in Verilator | native Wonderful-built fixture parses `日本語かな漢`; a dedicated verifier binds licensed Misaki Unicode/Shift-JIS rows to exact ROM/GDMA/tile/map/cell provenance and pixel-perfect output; `testroms/swan-song/sjis_glyph_provenance/README.md` |
| Trace-filter config | Verified with v5 CPU/GDMA/SDMA runtime | parser/serializer unit tests plus translated-model event selection, PC/address/offset containment, all three memory initiator filters, memory access/space/origin filters, and all six display roles; `trace.example.conf`, v1/v2/v3/v4/v5 CSV, and JSONL are documented |
| Translation-target acceptance | Not tested | no trace of the target 2001 WSC title has been captured or correlated with its kanji/glyph mapping |

The general Phase 1 v5 instrumentation is working end to end in the translated
model. Phase acceptance remains open because it specifically requires a useful text-renderer trace
from the target 2001 WSC title and correlation with that title's kanji/glyph
mapping. No commercial ROM is included or acquired by this project.

### Research-backed provenance step

Role and address identify which map/tile word the display requested. V3 adds
the filtered memory-transaction bridge: initiator, read/write, value,
write/DMA byte enable, exact CPU instruction identity/origin where provable, mapped
memory space, and resolved ROM/SRAM byte offset. This direction matches [Mesen's WonderSwan
memory-operation debugger](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/Debugger/WsDebugger.cpp#L149-L230)
and an open translation project's [far-pointer/charmap
workflow](https://github.com/JohnTsq/WS_Cardcaptor_Sakura_chs/blob/52c7d2b89865874cb2d6b538359f3ac76570471a/tools/TransMsg/TransMsg.c).
V4 proves the transport chain through the exact display word and writer present
on its fetch edge. V5 adds a narrower logical boundary for backgrounds: the map
word and decoded, contributing 2bpp/4bpp tile row promoted into the pixel
shifter, with writers frozen at their earlier raw-fetch edges. It does not claim
that a promoted cell survives windowing, transparency, layer/sprite priority,
or clipping, and a tile index is not automatically a character code. Phase 1
acceptance still needs
the user-owned target title trace and correlation of those transactions with
its specific glyph table and visible text.

The generated mapper probes prove the current resolver and observer, not every
underlying hardware behavior. In particular, this RTL returns zero for absent
SRAM, while pinned [ares returns cartridge open
bus](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cartridge/memory.cpp#L25-L38)
and pinned Mesen leaves its fallback behavior as an open-bus TODO. The probe
therefore locks the observed core value without calling it hardware-correct.
CPU reads use `byte_enable=0` as an observer convention because the functional
CPU only drives byte enables for writes; the field must not be read as CPU
operand width. The integrated top keeps the DMA engine's hardware path enabled
inside the translated model. A generated probe now proves four SDMA byte steps
and their exact linear-ROM provenance. [WSdev documents SDMA as byte-oriented](https://ws.nesdev.org/wiki/DMA),
but the inherited RTL's shared DMA bus drives raw `byte_enable=3`; the trace
records that signal without interpreting it as sample width. Current [WSdev header research](https://ws.nesdev.org/wiki/ROM_header)
also conflicts with the inherited `ramtype=0x01` SRAM size, so the runtime
fixture uses the unambiguous `0x03`/128 KiB declaration.

The SDMA probe covers one-shot, incrementing Channel 2 transfer provenance; it
does not prove full sound-DMA fidelity. Source review against [WSdev](https://ws.nesdev.org/w/index.php?title=DMA&oldid=562),
[pinned Mesen](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsDmaController.cpp#L46-L92),
and [pinned ares](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/apu/dma.cpp#L1-L33)
shows that inherited RTL does not implement hold semantics or live active-counter
writes as documented, and the open probe cannot establish the physical
`117 mod 128` phase or `6+N` stolen-cycle cost. Repeat, decrement, hold, Hyper
Voice targeting, resume behavior, and exact hardware timing remain open for a
later functional audit.

## Baseline corrections discovered

The attached brief's limitation list predates the pinned Pocket release. The
baseline already contains APF Memories/sleep-wake support, RTC logic, vertical
control remapping, triple buffering, and two/three-frame flicker blending.
Future phases must evaluate and improve those implementations rather than add
them as if absent.

The provenance audit also exposed and fixed a console-logic error: mono writes
above the documented 16 KiB IRAM range were classified unmapped but still
enabled the hidden 64 KiB backing RAM. The mono-unmapped branch now suppresses
that write enable; the open golden-frame regressions remain unchanged.

The open WSC extended-range fixture exposed a second console-logic error:
`SPR_BASE` bit 5 was incorrectly restricted to 4bpp, aliasing a 2bpp Color
sprite table at `0x5600` down to `0x1600`. The corrected Color-mode decode now
renders PASS and traces the exact extended table words, matching WSdev, ares,
and Mesen behavior.

The boot-overlay probe exposed a simulator initialization error: the model had
not observed its initial low clock level before the first BIOS-programming
cycle, so bytes 0/1 of a supplied boot image were skipped. The harness now
evaluates the initialized low clocks once, and both generated boot images must
execute successfully from byte zero. The mapper probe also exposed stale CPU
write-lane state on later read trace events; v5 now emits a deliberate zero
mask for CPU reads while retaining real masks for writes and DMA transfers.
