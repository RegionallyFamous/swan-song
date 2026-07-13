# Roadmap status

## Phase 0 — faithful rebuild

| Item | Status | Evidence |
| --- | --- | --- |
| History-preserving Pocket fork | Complete | current branch is based at Pocket `1.0.1` / `073213a2` and retains its ancestry |
| Upstream pins and license audit | Pins complete; license review open | `UPSTREAMS.md`; GPL v2 top-level Pocket/MiSTer licenses coexist with GPL-v3-or-later RTL headers; MIT utilities |
| Architecture and port boundary | Complete | `ARCHITECTURE.md`, `PORTING.md` |
| System simulation | Implemented for two open tests | deterministic GPU-framebuffer hashes via `make regression`; Pocket wrappers and SDRAM controller are outside this harness |
| PNG framebuffer output | Complete | `sim/verilator/rgb_to_png.py` |
| Optional waveform trace | Complete at whole-design VCD level | `--trace FILE.vcd` |
| Quartus bitstream | Blocked on host tool availability | requires supported Linux/Windows Quartus 21.1.1 host |
| Timing closure | Not tested | requires Quartus build |
| Hardware equivalence | Not tested | requires user-approved Pocket validation |

Phase 0 is not complete as a hardware deliverable until Quartus compilation,
timing closure, and optional device testing are performed. Phase 1 console
instrumentation has not begun.

## Baseline corrections discovered

The attached brief's limitation list predates the pinned Pocket release. The
baseline already contains APF Memories/sleep-wake support, RTC logic, vertical
control remapping, triple buffering, and two/three-frame flicker blending.
Future phases must evaluate and improve those implementations rather than add
them as if absent.
