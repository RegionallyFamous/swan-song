# Pocket Memories staging architecture

Status: **isolated control plane, structural/integrity/profile/device A4
preflight, bounded EEPROM load-settle ownership, plus a disabled production
ownership boundary are implemented and adversarially tested; no working
Memories path, fit, or hardware support is claimed.**
`savestate_supported` and `sleep_supported`
remain false. `apf_savestate_staging.sv` is intentionally absent from
`ap_core.qsf` until its SDRAM and clock-domain adapters exist. The smaller
`apf_sdram_channel1_mux.sv` is compiled in the live cartridge-ROM path, but its
staging request/acquire inputs are tied low.

## Why a complete staging image is mandatory

Analogue's documented order is unambiguous:

- For [`00A0 Savestate: Start/Query`](https://www.analogue.co/developer/docs/host-target-commands),
  Pocket requests creation, polls until the core reports done, and only then
  copies the blob out.
- For [`00A4 Savestate: Load/Query`](https://www.analogue.co/developer/docs/host-target-commands),
  Pocket first discovers the destination, copies the complete blob into the
  core, and only then sends Request Load. The
  [Core Boot Process](https://www.analogue.co/developer/docs/core-boot-process)
  states the same ordering.

The inherited controller does the opposite on load: it asserts the live
MiSTer restore as soon as its input FIFO becomes nonempty. That FIFO contains
4,096 32-bit words, only 16 KiB, while its save FIFO contains four 64-bit
words, only 32 bytes. The checked reference branches use the same streaming
pattern: pinned agg23 NES commit
[`c427ab0`](https://github.com/agg23/openfpga-nes/blob/c427ab08a91af43d2eab2073d0a7b1656972dd13/src/fpga/core/rtl/mister_top/save_state_controller.sv)
and pinned budude2 GBC commit
[`0be702f`](https://github.com/budude2/openfpga-GBC/blob/0be702f55eb864b532835f30b11790e4ba61170d/src/gb/save_state_controller.sv).
Those implementations are useful provenance, but their early-restore FIFO
behavior is not a safe APF Memories contract for Swan Song.

`apf_savestate_staging.sv` instead establishes these invariants:

1. A4 copy-in writes only an isolated staging backend.
2. The exact sequential `0x90320` SWAN blob must finish structurally valid.
3. Every one of the `0x90300` payload bytes must be accepted successfully by
   the backend before `restore_start` can pulse.
4. Only `restore_start` and restore-authorized reads may reach the live state
   engine. Bad magic/version/length/format, short or gapped input, backend
   failure, misalignment, or an unacknowledged final word cannot reach either.
5. A0 cannot authorize header or payload reads until the state engine has
   supplied every exact payload word and the backend has accepted them.
6. Payload reads are bounded and aligned independently for the A0 and restore
   phases. A new A4 offset-zero transaction invalidates the previous A0 image.

The compact RTL bench models the staging memory and treats `restore_start` as
the sole live-mutation edge. It covers short A0 capture, backend backpressure,
exact A0 publication, header/payload bounds, bad-magic/short/gapped/backend-error
A4 loads, simultaneous A0/A4 start, finalize with an unhandshaken valid, a
Request Load received while the final backend word is pending, legal held-valid
backpressure, bounded restore reads, and exactly one successful restore pulse.
All malformed cases leave the modeled live state untouched.

## Resource and address decision

The target `5CEBA4F23C8` is a Cyclone V E A4 device. Intel's current
[Cyclone V product table](https://cdrdv2-public.intel.com/714207/cyclone-v-product-table.pdf)
specifies 308 M10K blocks / 3,080 Kb, or 394,240 raw bytes, for the entire
device. The exact Memories blob is 590,624 bytes before any implementation
overhead, so it cannot fit in all device M10Ks even if the rest of the core
used none. The five framebuffer banks already target 200 M10Ks; the nominal
108-block remainder is only 138,240 raw bytes. MLAB capacity does not close
that gap, and a Quartus fitter report—not arithmetic—is still authoritative
for realized usage.

Pocket supplies this core a 512-Mbit ×16 SDRAM, 64 MiB, and the existing
controller exposes a 25-bit word address. The current byte ranges are:

| Range | Owner |
| --- | --- |
| `0x0000000..0x0ffffff` | Cartridge ROM, maximum implemented 16 MiB |
| `0x1000000..0x107ffff` | Maximum 512 KiB cartridge SRAM |
| `0x1100000..0x11902ff` | Isolated v1 transport fixture's proposed payload range; not a production target |
| `0x1100000..0x121ffff` | Frozen v2 payload staging reservation; the 256-byte envelope is synthesized separately |

The common staging base leaves a 512 KiB guard gap after maximum cartridge
SRAM. Production uses the fixed `0x120000`-byte v2 payload range defined and
compile-time checked by
[`SAVESTATE_V2_FORMAT.md`](SAVESTATE_V2_FORMAT.md) and its isolated layout
package. Those constants are not yet present in production RTL. The smaller
v1 range remains useful only for testing the fail-closed transport controller
and must never be enabled as Pocket Memories.

## Channel-1 ownership boundary

The existing ROM loader is the sole channel-1 client during startup and is
idle during gameplay, so borrowing that channel is safer than changing the
fixed-priority controller or adding a live fourth client. The compiled mux
latches every accepted request until its completion, gives a held ROM request
priority over acquisition, changes owner only after the prior request drains,
routes ready/data by the latched owner, preserves a ROM word held across stage
release, and makes illegal staging access a sticky fail-closed error. Its
focused bench covers all of those cases, including the full 25-bit staging
word address.

This is still only a disabled boundary. Channel 1 has priority over the
console's channel-3 cartridge/SRAM path. The controller now deterministically
clears request history, queues, read-delay pipelines, ready/data outputs, and
captured transaction state on PLL init; it exports a tested global
`quiescent` level covering queued edges, active commands, delayed reads,
ready/data capture, cooldown, refresh, and startup. `wonderswan.sv` also names
channel-2/channel-3 requests and retains channel-3 ready instead of discarding
it. Allowing staging traffic now could still delay a state-engine SRAM read
past its inherited fixed wait and return stale data. The staging side therefore
stays physically tied off until capture/restore is serialized and these drain
observations are consumed by an acknowledged coordinator.

The closest current community precedent found is mincer-ray's
[openFPGA-GBA v0.6.2 controller](https://github.com/mincer-ray/openfpga-GBA/blob/b08568fa60ff6f5f918cca5763f5b1923ed2d3db/src/fpga/core/save_state_controller.sv)
and [channel-1 top-level mux](https://github.com/mincer-ray/openfpga-GBA/blob/b08568fa60ff6f5f918cca5763f5b1923ed2d3db/src/fpga/core/core_top.sv#L723-L789).
That implementation validates channel 1 as a practical staging route, but its
small FIFOs, early A0 completion, unobserved inbound-full condition, OR-based
write selection, and lack of a drain acknowledgement are not copied here.

## Required production integration

The isolated module is a control-plane contract, not a storage implementation.
The current `0x90300` version-1 payload is also only a transport fixture: its
variable producer and omitted EEPROM/RTC/PPU/APU state cannot become a
production Memory. Integration requires all of the following:

1. Complete and freeze the v2 machine semantic ABI inside the already-fixed
   blob allocation by defining, implementing, and exporting every mutable
   machine register and memory listed in `SAVESTATE_V2_FORMAT.md`, including
   the still-opaque CPU, PPU, APU, mapper, scheduler, DMA, and live-I/O
   sections. Preserve the frozen allocation, header-field layout, deterministic padding,
   identity, integrity, and RTC/EEPROM device rules; assign executable section
   schemas before any v2 image is supported, and continue to reject the
   version-1 experiment.
2. Add a cooperative console pause boundary and consume the new SDRAM
   quiescence/completion observations in an acknowledged ownership coordinator.
   A0 must first let the inherited state engine reach `system_idle`; asserting
   external pause before that point can strand a mid-instruction CPU forever.
   Replace the state engine's current refresh-counter/fixed-delay SRAM heuristic
   with real channel-3 completion before staging is enabled.
3. Add lossless `clk_74a` ↔ `clk_mem_110_592` request/response crossings.
   Analogue's checked-in bridge peripheral says consecutive bridge words are
   at worst 88 clocks apart at 74.25 MHz, but the integration must still prove
   its maximum SDRAM arbitration latency and make any FIFO overflow observable.
   The physical bridge has no ready wire with which this module can stall
   Pocket, so a bare ready/valid connection is not sufficient.
4. Adapt the MiSTer manager's 64-bit, byte-enabled stream to exact 32-bit
   staging words without changing its payload ordering or silently discarding
   byte enables. Serialize each state-engine word completely through channel 1
   before acknowledging it, so staging can never overlap the following
   channel-3 SRAM access. Deterministically zero-pad smaller RAM-type captures
   to the new fixed payload size and lock endianness.
5. Give A0 bridge reads a bounded cache matching APF's buffered-read timing;
   synthesize the 32-byte header and fetch payload words from SDRAM only after
   `save_ready`. Read-ahead must stop before it can overlap a live channel-3
   state-engine operation.
6. Route A4 through the isolated v2 preflight and then through future
   per-subsystem semantic gates. The current preflight checks exact committed
   order/length, header and payload CRC64, identity and hard settings, profile
   zero padding, RTC/EEPROM controller schemas, bounded backend completion, and
   immutable stage generation. It deliberately does not interpret CPU, PPU,
   APU, mapper, scheduler, DMA, or live-I/O state yet. Every other staging
   writer, including A0 capture, must invalidate the result. No current
   `fifo_load_empty` shortcut may remain, and Reset Enter, title reload, menu
   interruption, PLL loss, or a new transaction must cancel safely without a
   delayed restore. The lossless A4 command frontend must count only durable
   word handshakes, wait for all buffered writes to commit, emit exactly one
   finalize event only for the complete v2 length, and latch the preflight's
   one-cycle terminal pulse as persistent busy/done/error state until Pocket's
   query lifecycle consumes it.
7. Define terminal success/failure behavior. A completed restore must flush and
   deterministically re-prime Pocket frame history; a pre-mutation failure may
   release pause, while an error after live mutation begins must remain safely
   stopped until a clean title reset.
8. Instantiate one proved load-settle guard per EEPROM and connect its separate
   retention/fault handshake to the atomic owner. Never OR the guard into the
   raw acknowledgement. Restore completion and release must wait for both raw
   EEPROM acknowledgements to return after synchronous-RAM settling. RTC stays
   on its direct, freeze-dominant raw acknowledgement path.

## Evidence still required before enabling

- Focused CDC and SDRAM-arbiter simulation at worst-case ROM/SRAM/state traffic,
  including refresh, bridge-rate bursts, stalls, resets, and injected errors.
- Compiled full-wrapper tests for A0 save/copy, A4 copy/request/restore, repeated
  cycles, duplicate bridge reads, interruption, and old/new-format rejection.
- Quartus Prime Lite 21.1.1 fit and TimeQuest evidence for M10K/MLAB/ALM changes,
  all clocks/crossings, no unexpected critical warnings, and nonnegative timing.
- Pocket and Dock validation across mono/Color, every cartridge RAM/EEPROM size,
  RTC, both orientations, active audio, turbo/fast-forward, title switching, and
  repeated Memories plus at least 50 distributed Sleep + Wake cycles.

Until every gate is satisfied, the correct first-class behavior is to keep
Memories and Sleep + Wake unavailable rather than expose a state path capable
of partially restoring or corrupting a running game.
