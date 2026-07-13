# Roadmap status

## Phase 0 — faithful rebuild

| Item | Status | Evidence |
| --- | --- | --- |
| History-preserving Pocket fork | Complete | current branch is based at Pocket `1.0.1` / `073213a2` and retains its ancestry |
| Upstream pins and license audit | Provenance complete; release clearance open | `UPSTREAMS.md`; MiSTer program notice is GPL v2-or-later and is version-compatible with GPL-v3-or-later RTL, but Pocket omitted that notice and the tree lacks a GPL v3 license copy |
| Architecture and port boundary | Complete | `ARCHITECTURE.md`, `PORTING.md` |
| System simulation | Implemented for open tests | deterministic GPU-framebuffer hashes for two checked-in MiSTer tests, Wonderful's mono 80186-quirks, SoC-interrupt, and WSC extended-range fixtures, the native Shift-JIS/Misaki glyph fixture, paired build-generated planar/packed 4bpp probes, and build-generated Color sprite-priority and interrupt/input probes via `make regression`, plus a pinned Wonderful `initfini` pass recorded in `WONDERFUL_VALIDATION.md`; generated probe binaries are not checked in; Pocket wrappers and SDRAM controller are outside this harness |
| V30MZ instruction quirks | Value, flag, exception, and memory-side-effect behavior verified in translated RTL | pinned open `80186_quirks.ws` renders three upstream-authored PASS results for D4/AAM and D5/AAD with base 16 plus D6/SALC; a separate build-generated probe records 24 exact results covering defined AAM flags, full AAD byte-ADD flags, D4 base-zero vector 0/post-IP/AX state, and D6 values with AH plus full before/after PUSHF words preserved and no data-memory access; exact hardware timing remains reference-correlated rather than trace-measured |
| SoC interrupt controller | UART-TX level, vector/status/ACK, and keypad-edge paths verified in translated RTL | pinned open `interrupts.ws` renders all 13 real-hardware-authored PASS results in two byte-identical six-frame runs and remains at its exact terminal loop; a separate build-generated Color probe proves `$B0` F8 alignment, disabled-edge isolation, actual key dispatch through vector `$81`, held/release/repress edge behavior, mask-independent pending retention, ACK, and exact combined-row values through the deterministic `BDVIHRPACZ` marker; UART receive/transmit timing, cartridge IRQ, and exact interrupt latency remain open |
| Simulation CI | Immutable workflow contract; remote run open | checkout is pinned by full SHA; official Verilator 5.050/GCC 13.3.0 and GHDL 6.0.0 images are digest-pinned and version-checked before `make regression`; the Ubuntu runner still supplies platform-managed shell/Make/Python; the current branch has not been pushed to a configured fork, so no remote green run is claimed |
| PNG framebuffer output | Complete | `sim/verilator/rgb_to_png.py` |
| Optional waveform trace | Complete at whole-design VCD level | `--trace FILE.vcd` |
| Structured event trace | V5/v6 runtime verified in Verilator | simulation-gated CPU, bank-register, completion-aligned display word/collision, completed CPU/GDMA/SDMA memory, atomic Screen 1/2 background-cell taps, and conditional atomic sprite-row taps; v5/v6 CSV/JSONL with v1-v6 CSV fixtures; translated open/generated-ROM regression plus focused atomic decode/grouping/writer-snapshot tests pass; `sim/verilator/TRACE.md` |
| Trace-to-frame artifact binding | Opt-in manifest v2 verified | `--trace-frame-artifacts` preserves v5/v6 trace bytes while binding every raw 224×144 RGB888 artifact to its zero-based final-pixel cycle, manifest-relative path, exact 96,768-byte size, and FNV-1a digest; atomic frame publication plus a strict artifact verifier reject mutation, symlink/hardlink/trace aliasing, field/count/index/cycle/path errors, and incomplete bundles while legacy manifest v1 remains unchanged; publication cycles are not claimed as hardware VBlank or blanket pixel causality |
| APF package assembly | Offline path verified; final RBF unavailable | `package_core.py` reverses a supplied RBF, materializes the exact 259-byte Chip32 loader declared by `core.json`, rejects changed source/image identities and unsafe/missing references, and emits byte-identical ZIPs for identical inputs; focused tests inspect both required payloads and prove stale-output invalidation; no Quartus bitstream has been packaged |
| Reproducible build identity | Generator verified; full RBF proof open | the APF pre-flow MIF uses a clean source commit, its UTC commit timestamp or explicit `SOURCE_DATE_EPOCH`, and a commit-derived 32-bit identity; focused tests prove identical output across repeats/timezones plus fail-closed dirty, mismatched, malformed, and non-Git inputs; two Quartus builds have not been compared |
| Quartus bitstream | Blocked on host tool availability | requires supported Linux/Windows Quartus 21.1.1 host |
| Timing closure | Not tested | requires Quartus build |
| Hardware equivalence | Not tested | requires user-approved Pocket validation |

Phase 0 is not complete as a hardware deliverable until Quartus compilation,
timing closure, and on-device Pocket testing are performed.

## Phase 1 — debug instrumentation

This section records Phase 1 groundwork while Phase 0's Quartus, timing, and
authorized Pocket gates remain unavailable. It does not declare Phase 0
deferred or Phase 1 accepted.

| Item | Status | Evidence needed or available |
| --- | --- | --- |
| ROM bank-switch writes | Verified with generated open probe | `make regression` executes distinct byte writes to C0-C3 plus a word write spanning C0-C1, and requires their exact accepted sequence, nonzero instruction IDs, and origin PCs (`0xf0003`, `0xf0007`, `0xf000b`, `0xf000f`, `0xf0014`); both bytes of the word write share one instruction identity; no probe binary is checked in |
| Deterministic controller replay | Verified through translated keypad and key-IRQ RTL | strict full-state scripts address physical `x1`-`x4`, `y1`-`y4`, Start/A/B at exact reset-relative system cycles; the mono routing probe proves X2 press/release through port B5 with no-input isolation and exact `INP`, while the Color interrupt probe proves exact combined X2+Y1 `B5=0x33`, released `B5=0x30`, key-edge IRQ isolation/dispatch/retention/ACK, exact `BDVIHRPACZ`, paired byte identity, raw+normalized manifest binding, and adversarial mutation rejection; user-owned title routing remains private and target-specific |
| VRAM/character fetch addresses | Raw and atomic runtime paths verified | open-ROM regression requires all six Screen 1/2 map/tile and sprite table/tile roles with aligned completion data and collision status; v5 binds a promoted background map word to decoded tile attributes and its contributing row, while conditional v6 binds a cached sprite descriptor and contributing row to its accepted line-buffer slot; the open Shift-JIS fixture binds six licensed Misaki characters to exact ROM offsets, GDMA tile writers, CPU map writers, 96 promoted rows, and final pixels; paired generated probes bind 4bpp planar/packed rows and all flip modes through exact ROM sources to identical final pixels; title-specific glyph provenance remains open |
| CPU PC ranges | Verified with running ROMs | regression checks `CS:IP` against wrapped physical PC and disjoint range-union containment; Wonderful execution terminates at the expected `0xff68b` loop |
| Memory provenance | All eight trace-space labels runtime verified with generated open probes | paired complete-from-reset traces require 36,817 memory plus five bank events each and exact `iram`, `cart_sram`/`absent_sram`, `cart_rom0`, `cart_rom1`, `cart_rom_linear`, `boot_rom`, and mono `unmapped` behavior; checks bind ROM/boot inputs, values, masks, offsets, CPU origins, ROM aliases, and the separate GDMA chains |
| CPU ROM-to-IRAM provenance | Strictly verified for the trace-observed bootstrap `REP MOVSB` copies | conservative classification requires an `F3 A4` origin signature plus an immediate exact same-instruction ROM-read/IRAM-byte-write pair; a dedicated verifier binds the canonical open ROM, complete v5 manifest, uninterrupted alternating chains, ranges, lanes, and all 4,096 byte values; bootstrap yields two 2,048-byte chains, ROM `0x00252..0x00a51` to IRAM `0x2800..0x2fff` and ROM `0x00a52..0x01251` to IRAM `0x2000..0x27ff`, totaling two origins, 52,512 display words, and 26,222 atomic cells whose contributing tile-row bytes are MOVSB-sourced; extended-range and Shift-JIS fixtures are zero for all four counts, and `unattributed` alone is not treated as proven prefetch |
| Sound-DMA provenance | Runtime verified with generated open WSC probe | the `sdma` filter returns exactly four one-shot linear-ROM reads at `0xf0100..0xf0103`, with exact returned words, mapped offsets, no CPU origin, and 1,536 trace-clock/128 CPU-clock cadence; raw inherited `byte_enable=3` is recorded without treating it as the one-byte sample width |
| Boot-ROM overlay and lockout | Runtime verified for mono and Color models | generated 4 KiB/8 KiB open test images execute from byte zero, read exact markers at `0xff100`/`0xfe100`, write A0 lockout, then require physical addresses `0xffff0..0xffffe` to change from mono boot offsets `0xff0..0xffe` or Color offsets `0x1ff0..0x1ffe` to cartridge offsets `0x1fff0..0x1fffe`; no proprietary firmware is used |
| Display-to-writer correlation | Verified on open regression | complete-from-reset manifest plus byte-lane IRAM scoreboard matches all 78,940 physical fetches: 78,750 exact CPU writers, 190 defined power-up prefetches, zero mismatches/collisions; `correlate_provenance.py` |
| Atomic background-cell correlation | Verified on open regression | `correlate_bg_cells.py` independently groups Screen 1/2 map/tile reads, validates 2bpp selected-word and 4bpp two-word rows, and snapshots byte writers/GDMA sources at the raw-fetch edge; regression validates 26,224 bootstrap cells, 5,176 extended-range Color cells, 8,307 Shift-JIS fixture cells, and 8,493 cells in each generated 4bpp format, with no atomic mismatch/collision |
| Atomic sprite-row correlation | Verified in translated RTL on open/generated probes | `correlate_sprite_rows.py` independently binds each promotion to its exact latched raw OAM generation, line-load epoch, exact two-read tile group, and fetch-time byte writers/sources; it locks the one-cycle admission edge and contiguous per-epoch slots, including focused slot-31, interleaved-DMA, repeated-line, and identical-refresh mutations; the open extended-range fixture covers 32 planar 2bpp rows and separates 32 noncontributing second reads, while the generated Color-priority probe covers 48 packed 4bpp rows sourced through GDMA; this stops at line-buffer admission, before X/window/transparency/priority/composition |
| Color 4bpp format equivalence | Verified in translated RTL | repository-authored, build-generated, non-checked-in probes select planar `0xc0` and packed `0xe0`, copy distinct 32-byte tile payloads by exact GDMA chains, display normal/H/V/HV placements, and require 64 provenance-complete diagnostic rows plus identical reporter fingerprints and final RGB across both encodings |
| Open Japanese text workload | Verified in Verilator | native Wonderful-built fixture parses `日本語かな漢`; a dedicated verifier binds licensed Misaki Unicode/Shift-JIS rows to exact ROM/GDMA/tile/map/cell provenance and pixel-perfect output; `testroms/swan-song/sjis_glyph_provenance/README.md` |
| Glyph candidate report | Verified on open Japanese fixture | `report_glyphs.py` emits a deterministic, title-agnostic epoch CSV and labeled contact PNG across 2bpp/4bpp planar/packed formats and both flips; regression preserves all 592 fixture epochs while the compact unique-exact view surfaces seven bitmaps and binds the six ROM-sourced glyph candidates to their exact fingerprints, map slots, writers, IRAM spans, and source offsets; it never infers character identity |
| Trace-filter config | Verified with v5/v6 CPU/GDMA/SDMA/display runtime | parser/serializer unit tests plus translated-model event selection, PC/address/offset containment, all three memory initiator filters, memory access/space/origin filters, all six display roles, conditional sprite-row schema, and legacy stability; `trace.example.conf`, v1-v6 CSV, and JSONL are documented |
| Translation-target acceptance | Not tested | no trace of the target 2001 WSC title has been captured or correlated with its kanji/glyph mapping |

The general Phase 1 v5/v6 instrumentation is working end to end in the translated
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
or clipping, and a tile index is not automatically a character code. V6 adds
the analogous descriptor/row-to-line-slot boundary for sprites without
claiming X visibility, window/transparency, priority, palette RGB, or final
pixel survival. Phase 1
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

The generated Color sprite-priority probe exposed a third console-logic error:
the Color mixer lacked the grayscale path's high-priority fallback. An earlier
low-priority sprite hidden by opaque Screen 2 therefore suppressed a later
high-priority sprite. The corrected ladder renders four exact blue/green/green/
red control panels and binds both OAM snapshots, all sprite-tile reads, the
ROM-to-IRAM GDMA chain, CPU setup writes, and the stable final frame. This is
verified in translated RTL only; it is not an on-device claim.

The open Wonderful CPU fixture exposed a fourth console-logic error: D4/AAM
and D5/AAD ignored their immediate base, while D6 incorrectly followed the D7
XLAT memory path. The shared V30MZ RTL now consumes the unsigned D4/D5 base,
raises vector 0 for D4 base zero after fetching the immediate, and implements
the eight-clock D6/SALC value behavior without a data-memory read. Defined
AAM flags derive from the result low byte; AAD uses the full low-byte ADD flag
model on which pinned ares and Mesen agree. The open upstream-authored ROM
proves the three value results in translated RTL. A generated, self-contained
probe now verifies the flag, exception-return, and no-data-memory contracts
through 24 exact IRAM records plus complete CPU/memory history. The eight-clock
SALC setting remains reference-correlated: prefetch-buffer credit makes the
observer's end-to-end completion delta unsuitable as an isolated hardware
timing measurement.

The pinned open interrupt fixture exposed a fifth console-logic error cluster.
The inherited controller sourced only display/timer interrupts, cleared pending
bits when their enables were written, returned the raw and model-mismasked B0
base, and acknowledged only a subset of sources. The corrected path aligns the
base to eight vectors on every model, returns the highest pending status index,
retains status across mask changes, acknowledges all eight bits, and connects
the enabled-and-ready UART-TX level source. The keypad now wired-ORs every
selected matrix row and raises a CE-safe interrupt only on selected-input rising
edges. This matches pinned [WSdev interrupt revision 553](https://ws.nesdev.org/w/index.php?title=Interrupts&oldid=553),
[WSdev UART behavior](https://ws.nesdev.org/wiki/UART), pinned ares
[interrupt](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cpu/interrupt.cpp#L1-L27)
and [keypad](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cpu/keypad.cpp#L1-L57)
models, and pinned Mesen's
[controller](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsMemoryManager.cpp)
behavior. The upstream
[hardware-authored fixture](https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/src/mono/soc/interrupts/main.c)
proves its eight UART-TX and five vector/status assertions through exact final
pixels. The generated Color/input probe additionally proves the actual vector
81h handler path, disabled and held-key isolation, release/repress, retained
pending status, full ACK, and simultaneous-row readback. The UART remains a
ready-only stub: receive, transmitted-byte timing, cartridge IRQ, and precise
interrupt latency are not established by this milestone.

The boot-overlay probe exposed a simulator initialization error: the model had
not observed its initial low clock level before the first BIOS-programming
cycle, so bytes 0/1 of a supplied boot image were skipped. The harness now
evaluates the initialized low clocks once, and both generated boot images must
execute successfully from byte zero. The mapper probe also exposed stale CPU
write-lane state on later read trace events; v5 now emits a deliberate zero
mask for CPU reads while retaining real masks for writes and DMA transfers.
