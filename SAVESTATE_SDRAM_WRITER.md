# Isolated savestate SDRAM writer

Status: **implemented and adversarially tested in isolation; not in the QSF,
not connected to the live SDRAM controller, and not evidence that Memories or
Sleep + Wake are supported.**

## Source-pinned design basis

Official Analogue documentation, rechecked 2026-07-13:

- [`00A0 Savestate: Start/Query` and `00A4 Savestate: Load/Query`](https://www.analogue.co/developer/docs/host-target-commands)
  define an opaque 32-bit-sized blob. A0 is created and reported done before
  Pocket reads it. A4 gives Pocket a destination and maximum size; Pocket
  writes the blob before sending Request Load.
- The [Core Boot Process](https://www.analogue.co/developer/docs/core-boot-process)
  gives the same ordering: support is queried first, A0 copy-out follows core
  completion, and A4 Request Load follows Pocket's complete copy-in.
- [External Hardware](https://www.analogue.co/developer/docs/external-hardware)
  identifies Pocket SDRAM as a 64 MiB x16 AS4C32M16MSA-6BIN device with
  byte-lane masks and recommends burst access where practical.

Mature public implementations used as architectural precedents:

- TheDiscordian/openfpga-pacman commit
  [`810df287dd39da1ea4c239b83d6f5c7d685c80d3`](https://github.com/TheDiscordian/openfpga-pacman/blob/810df287dd39da1ea4c239b83d6f5c7d685c80d3/SAVESTATES.md)
  stages its complete small state before publication and freezes the whole
  emulated machine during serialization. Its M10K-sized shadow is a useful
  correctness precedent but cannot hold Swan Song's `0x90300`-byte payload.
- mincer-ray/openfpga-GBA commit
  [`b08568fa60ff6f5f918cca5763f5b1923ed2d3db`](https://github.com/mincer-ray/openfpga-GBA/blob/b08568fa60ff6f5f918cca5763f5b1923ed2d3db/src/fpga/core/save_state_controller.sv)
  demonstrates large-state SDRAM staging and x32/x64-to-x16 decomposition.
  Swan Song does not inherit its unreported FIFO-full condition or streaming
  A0 publication behavior.
- Swan Song's unchanged inherited SDRAM arbiter comes from agg23/openfpga-
  wonderswan commit
  [`1cce8962b8da8e663ac82c0c95c83488e33aa742`](https://github.com/agg23/openfpga-wonderswan/blob/1cce8962b8da8e663ac82c0c95c83488e33aa742/src/fpga/core/rtl/sdram.sv).
  It captures request rising edges, emits one-cycle ready pulses, uses x16
  burst-length-one accesses, gives emergency refresh first priority, and then
  arbitrates channels 1, 2, and 3 in fixed order.

## Implemented contract

`src/fpga/core/apf_savestate_sdram_writer.sv` is a memory-clock-domain
write-only adapter. It does not contain the required `clk_74a` to SDRAM CDC
FIFO and must never be wired directly to the physical APF bridge, which has no
ready signal with which this module could stall Pocket.

Each accepted `{payload_offset, normalized_word}` is handled as follows:

1. Require a four-byte-aligned offset wholly inside payload range
   `0x00000000..0x000902ff`.
2. Add it to protected byte base `0x01100000` with a wide, checked addition.
3. Pulse one request for the low x16 address and wait for ready.
4. Pulse a distinct request for the adjacent high x16 address and wait again.
5. Pulse logical commit and add four committed bytes only if both halves
   succeeded.

The implemented physical payload range is `0x01100000..0x011902ff`. Its x16
word range is `0x00880000..0x008c817f`. Four-byte word `0x11223344` is
normalized as blob bytes `11 22 33 44` and written as x16 values `0x2211` then
`0x4433`, so low DQ byte remains the lower byte address.

Input ready deasserts from word acceptance through both acknowledgements.
Requests are exactly one cycle and have a low interval between halves, matching
the inherited controller's rising-edge capture. Address and data remain stable
while an issued half waits for ready.

Atomicity is deliberately logical rather than physical. SDRAM cannot roll back
an already completed low half. Abort, invalid address, or backend error clears
transaction-active, sets a sticky failure reason, prevents commit, and makes
the entire staging image unauthorized. A new transaction can clear that state
only when no old request is outstanding. Abort after request issue enters a
drain state—even if abort remains asserted—until its ready pulse arrives,
preventing that stale acknowledgement from being mistaken for a request in the
next transaction.

## Explicit assumptions and remaining work

- `sdram_ready` is exactly one completion pulse for the outstanding request;
  `sdram_error` is meaningful only with that pulse. The inherited controller
  currently has no error output, so a future production connection would tie
  it low unless stronger backend monitoring is added.
- Reset during an outstanding request is safe only when the writer and SDRAM
  arbiter are reset together. The test and module document this rather than
  pretending a stale physical response can be identified after local reset.
- The upstream envelope coordinator owns exact sequential offsets, total byte
  count, CRC, and finalization. This writer independently owns range safety and
  two-half commit; it intentionally permits valid in-range random offsets for
  future zero-fill/readback workflows.
- A lossless, full-observed dual-clock FIFO is still required in front of this
  module. Existing four-entry APF loaders with unconnected full flags are not
  an acceptable substitute.
- A fourth SDRAM client and bounded ch3/ch4 arbitration are still required.
  This slice does not edit `sdram.sv` or prove refresh/contention timing.
- The paired isolated reader now covers checked x16 read/reassembly and a
  stable one-word cache. Durable CRC orchestration, A0 cache priming, restore,
  Quartus fit/timing, and Pocket hardware validation remain unimplemented.

The dedicated Verilator regression covers protected first/last addresses,
normalization, independent low/high stalls, held-valid backpressure, one-cycle
requests, no commit after only one half, malformed/misaligned/overflow offsets,
backend errors on either half, abort before issue, abort during either
outstanding half, stale-ready drain, restart recovery, and 256 randomized
in-range words with independently randomized stalls.
