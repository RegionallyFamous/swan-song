# Roadmap status

## Phase 0 — faithful rebuild

| Item | Status | Evidence |
| --- | --- | --- |
| History-preserving Pocket fork | Complete | current branch is based at Pocket `1.0.1` / `073213a2` and retains its ancestry |
| Upstream pins and license audit | Provenance complete; release clearance open | `UPSTREAMS.md`; MiSTer program notice is GPL v2-or-later and is version-compatible with GPL-v3-or-later RTL, but Pocket omitted that notice and the tree lacks a GPL v3 license copy |
| Architecture and port boundary | Complete | `ARCHITECTURE.md`, `PORTING.md` |
| System simulation | Implemented for open tests | deterministic GPU-framebuffer hashes for two checked-in MiSTer tests via `make regression`, plus a pinned Wonderful `initfini` pass recorded in `WONDERFUL_VALIDATION.md`; Pocket wrappers and SDRAM controller are outside this harness |
| PNG framebuffer output | Complete | `sim/verilator/rgb_to_png.py` |
| Optional waveform trace | Complete at whole-design VCD level | `--trace FILE.vcd` |
| Structured event trace | Verified in Verilator | simulation-gated CPU, bank-register, and GPU VRAM taps; CSV/JSONL logging; automated CPU/VRAM and generated C0-C3 bank-probe checks; `sim/verilator/TRACE.md` |
| Quartus bitstream | Blocked on host tool availability | requires supported Linux/Windows Quartus 21.1.1 host |
| Timing closure | Not tested | requires Quartus build |
| Hardware equivalence | Not tested | requires user-approved Pocket validation |

Phase 0 is not complete as a hardware deliverable until Quartus compilation,
timing closure, and optional device testing are performed.

## Phase 1 — debug instrumentation

| Item | Status | Evidence needed or available |
| --- | --- | --- |
| ROM bank-switch writes | Verified with generated open probe | `make regression` executes C0-C3 writes with distinct values and requires all four serialized addresses; no probe binary is checked in |
| VRAM/character fetch addresses | Runtime path verified | open-ROM regression requires valid `vram` records; the Wonderful `initfini` trace records 2,163,360 graphics fetches while rendering known text, but title-specific glyph-address correlation remains open |
| CPU PC ranges | Verified with running ROMs | regression checks `CS:IP` against wrapped physical PC and range containment; Wonderful execution terminates at the expected `0xff68b` loop |
| Trace-filter config | Verified | parser/serializer unit test plus translated-model event selection and PC-filter regression; `trace.example.conf`, CSV, and JSONL are documented |
| Translation-target acceptance | Not tested | no trace of the target 2001 WSC title has been captured or correlated with its kanji/glyph mapping |

The general Phase 1 instrumentation is working end to end in the translated
model. Phase acceptance remains open because it specifically requires a useful
text-renderer trace from the target 2001 WSC title and correlation with that
title's kanji/glyph mapping. No commercial ROM is included or acquired by this
project.

## Baseline corrections discovered

The attached brief's limitation list predates the pinned Pocket release. The
baseline already contains APF Memories/sleep-wake support, RTC logic, vertical
control remapping, triple buffering, and two/three-frame flicker blending.
Future phases must evaluate and improve those implementations rather than add
them as if absent.
