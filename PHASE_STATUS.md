# Roadmap status

## Phase 0 — faithful rebuild

| Item | Status | Evidence |
| --- | --- | --- |
| History-preserving Pocket fork | Complete | current branch is based at Pocket `1.0.1` / `073213a2` and retains its ancestry |
| Upstream pins and license audit | Provenance complete; release clearance open | `UPSTREAMS.md`; MiSTer program notice is GPL v2-or-later and is version-compatible with GPL-v3-or-later RTL, but Pocket omitted that notice and the tree lacks a GPL v3 license copy |
| Architecture and port boundary | Complete | `ARCHITECTURE.md`, `PORTING.md` |
| System simulation | Implemented for open tests | deterministic GPU-framebuffer hashes for two checked-in MiSTer tests and Wonderful's WSC extended-range fixture via `make regression`, plus a pinned Wonderful `initfini` pass recorded in `WONDERFUL_VALIDATION.md`; Pocket wrappers and SDRAM controller are outside this harness |
| PNG framebuffer output | Complete | `sim/verilator/rgb_to_png.py` |
| Optional waveform trace | Complete at whole-design VCD level | `--trace FILE.vcd` |
| Structured event trace | Verified in Verilator | simulation-gated CPU, bank-register, completion-aligned display word/collision, and completed CPU/GDMA/SDMA memory taps; v4 CSV/JSONL with v1/v2/v3 CSV verification; automated all-role, address, value, PC, exact CPU-origin, C0-C3 bank, and ROM-to-IRAM GDMA checks; `sim/verilator/TRACE.md` |
| Quartus bitstream | Blocked on host tool availability | requires supported Linux/Windows Quartus 21.1.1 host |
| Timing closure | Not tested | requires Quartus build |
| Hardware equivalence | Not tested | requires user-approved Pocket validation |

Phase 0 is not complete as a hardware deliverable until Quartus compilation,
timing closure, and optional device testing are performed.

## Phase 1 — debug instrumentation

| Item | Status | Evidence needed or available |
| --- | --- | --- |
| ROM bank-switch writes | Verified with generated open probe | `make regression` executes C0-C3 writes with distinct values and requires all four serialized addresses; no probe binary is checked in |
| VRAM/character fetch addresses | Runtime roles and fetched words verified | open-ROM regression requires all six Screen 1/2 map/tile and sprite table/tile roles with aligned completion data and collision status; the open WSC fixture proves map `0x5a20`, bank-1 tile `0x5fc0`, and 2bpp Color sprite table `0x5600`; title-specific glyph provenance remains open |
| CPU PC ranges | Verified with running ROMs | regression checks `CS:IP` against wrapped physical PC and range containment; Wonderful execution terminates at the expected `0xff68b` loop |
| Memory provenance | Linear ROM/IRAM verified with generated open WSC probe; other mappings RTL-reviewed | completed CPU/GDMA/SDMA transaction schema includes value, raw byte enable, distinct mapped space, exact resolved byte offset, and honest CPU origin status; regression proves two ordered GDMA ROM-read/IRAM-write value pairs |
| Display-to-writer correlation | Verified on open regression | complete-from-reset manifest plus byte-lane IRAM scoreboard matches all 78,760 fetched words: 78,754 exact CPU writers, six power-up words, zero mismatches/collisions; `correlate_provenance.py` |
| Trace-filter config | Verified | parser/serializer unit test plus translated-model event selection, PC/address/offset containment, memory initiator/access/space/origin filters, and all six display roles; `trace.example.conf`, v1/v2/v3/v4 CSV, and JSONL are documented |
| Translation-target acceptance | Not tested | no trace of the target 2001 WSC title has been captured or correlated with its kanji/glyph mapping |

The general Phase 1 instrumentation is working end to end in the translated
model. Phase acceptance remains open because it specifically requires a useful
text-renderer trace from the target 2001 WSC title and correlation with that
title's kanji/glyph mapping. No commercial ROM is included or acquired by this
project.

### Research-backed provenance step

Role and address identify which map/tile word the display consumed. V3 now adds
the missing filtered memory-transaction bridge: initiator, read/write, value,
raw byte enable, exact CPU instruction identity/origin where provable, mapped
memory space, and resolved ROM/SRAM byte offset. This direction matches [Mesen's WonderSwan
memory-operation debugger](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/Debugger/WsDebugger.cpp#L149-L230)
and an open translation project's [far-pointer/charmap
workflow](https://github.com/JohnTsq/WS_Cardcaptor_Sakura_chs/blob/52c7d2b89865874cb2d6b538359f3ac76570471a/tools/TransMsg/TransMsg.c).
The open regression now proves the transport chain through the exact display
word and last observed IRAM writer. Phase 1 acceptance still needs
the user-owned target title trace and correlation of those transactions with
its specific glyph table and visible text.

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
