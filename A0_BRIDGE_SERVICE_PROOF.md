# A0 BRIDGE service and prefetch proof

Status: **isolated timing model; current production result is fail closed. No
finite streaming FIFO depth is proven for the present Swan SDRAM arbitration,
the model is not in the QSF, and Memories remains disabled.**

## Pinned BRIDGE behavior

Official sources were rechecked 2026-07-13:

- Analogue's [Bus Communication](https://www.analogue.co/developer/docs/bus-communication)
  says BRIDGE has no core-visible wait/arbitration signal. A read result may be
  produced after its strobe, but must be driven before the next read strobe.
- The current linked official template is open-fpga/core-template commit
  [`da3a021b1eaf742604d86d8dc9b33a6666263e6a`](https://github.com/open-fpga/core-template/blob/da3a021b1eaf742604d86d8dc9b33a6666263e6a/src/fpga/apf/io_bridge_peripheral.v#L38-L50).
  Its `io_bridge_peripheral` states that reads are buffered by one word and
  that the fastest/worst-case transaction cadence is one word every 88 cycles
  at 74.25 MHz, about 1.185 microseconds.
- The implementation makes that pipeline concrete: `ST_READ_0` returns the
  current `pmp_rd_data` value, then `ST_READ_1` pulses `pmp_rd` to start the
  value needed by the next transaction. There is no `ready` input from the
  core and no retry path.
- The local `src/fpga/apf/io_bridge_peripheral.v` is byte-identical to that
  official commit. Its local last-modifying commit is
  `8aee749c516133039fc1c539bf5b8ad9ac71731d`.

Current maintained Memories-capable cores retain the same APF timing model:

- agg23/openfpga-NES master
  [`a09c51e2487686a862d5ec660f515c4c2e0301b5`](https://github.com/agg23/openfpga-NES/blob/a09c51e2487686a862d5ec660f515c4c2e0301b5/platform/pocket/io_bridge_peripheral.v)
  has behavior identical to the official peripheral apart from whitespace.
  Its [Pocket top](https://github.com/agg23/openfpga-NES/blob/a09c51e2487686a862d5ec660f515c4c2e0301b5/target/pocket/core_top.v#L390-L395)
  publishes `0x40000000` and directly muxes `0x4xxxxxxx` to its core-specific
  savestate RAM path.
- budude2/openfpga-GBC master
  [`864253c6c2d902208db387caabb031574cdd8a5e`](https://github.com/budude2/openfpga-GBC/blob/864253c6c2d902208db387caabb031574cdd8a5e/src/apf/io_bridge_peripheral.v)
  is byte-identical to the official peripheral. Its
  [Pocket top](https://github.com/budude2/openfpga-GBC/blob/864253c6c2d902208db387caabb031574cdd8a5e/src/core/core_top.sv#L305-L308)
  also publishes `0x40000000` and uses a direct `0x4xxxxxxx` savestate mux.

Those cores confirm the deployed one-word pipeline. Their private RAM paths do
not prove service for Swan Song's `0x90300`-byte SDRAM-backed payload.

## Exact demand rate

Swan's bridge is 74.25 MHz and its SDRAM clock is 110.592 MHz, pinned in
`src/fpga/core/mf_pllbase.v`. The fastest official BRIDGE cadence expressed in
memory-clock cycles is therefore exactly:

```
88 * 110,592,000 / 74,250,000 = 16,384 / 125 = 131.072 cycles/word
```

The protected payload has `0x90300 / 4 = 147,648` x32 words. The header is a
small separate mux concern; the model defaults to the large payload because it
dominates SDRAM service and can be overridden for a future complete envelope.

The isolated reader serializes two x16 reads. If a reviewed arbiter guarantees
that each request edge receives ready within at most `B` memory cycles, the
reader's steady cached-word completion interval is modeled as:

```
S = 2*B + 3 memory cycles
```

The three local cycles cover cache handoff/successor acceptance and the two
distinct request-issue edges. Any future CDC or wrapper latency must be added
to that overhead; the default is not permission to omit it.

## Why the current result is unbounded

Swan's SDRAM controller remains the implementation from agg23/openfpga-
wonderswan commit
[`1cce8962b8da8e663ac82c0c95c83488e33aa742`](https://github.com/agg23/openfpga-wonderswan/blob/1cce8962b8da8e663ac82c0c95c83488e33aa742/src/fpga/core/rtl/sdram.sv).
It captures request edges and, after emergency refresh, checks pending clients
in fixed order `ch1`, `ch2`, `ch3`. There is no `ch4`, round-robin rotation,
age counter, maximum burst, or reservation for Memories.

A higher-priority client can arrange for its next request to be pending each
time the controller returns to idle. A hypothetical lower-priority Memories
request can consequently wait forever. Emergency refresh adds a finite pause,
but cannot turn fixed priority into a service guarantee. Pausing the emulated
CPU may reduce traffic in practice; it is not a proof that ROM loading, save
RAM activity, DMA/external RAM, CDC residue, and every pending request have
quiesced.

Therefore `B` is infinite/unproven in the production design. No streaming FIFO
depth can be certified, and A0 must continue to report unsupported. The only
buffer-only escape is to prefetch the complete payload into *independent,
proven* storage before publishing A0: 147,648 words / 590,592 bytes. No such
independent full-copy store is implemented or resource-proven here.

## Isolated model and conditional results

`scripts/apf_a0_prefetch_service_model.py` is an event-accurate, rational-clock
model. It assumes the FIFO is completely prefetched before A0 publication,
then runs the slowest legal single producer against the fastest legal host for
all 147,648 words. A configurable setup margin requires the head word to be
present before each actual strobe. The default margin is two memory clocks.

With no explicit halfword bound, the tool exits 2 and reports:

```
status = unproven
minimum_fifo_depth_words = null
full_blob_prefill_words = 147648
```

Example conditional invocation—not a production claim:

```
python3 scripts/apf_a0_prefetch_service_model.py \
  --halfword-service-bound-mem-cycles 15 \
  --verify-depth-words 1
```

That hypothetical bound gives `S=33`, comfortably below the effective next-
word deadline, so one completely prefetched word passes. More generally, with
the pinned clocks, three-cycle reader overhead, and two-cycle setup margin:

- `B <= 63`: one prefetched word passes.
- `B = 64`: `S=131`; one word misses setup, while two words pass.
- `B = 65`: `S=133`, slower than host demand; the full payload needs 2,142
  initially prefetched words (8,568 bytes) even if that bound is perfectly
  enforced.
- No finite `B`: no streaming result is emitted.

The simulator dynamically models FIFO capacity, an in-flight serialized read,
late-but-useful completions, setup deadlines, and actual pop times. Constant
maximum producer latency and minimum host spacing dominate every
work-conserving trace with the asserted bounds. The tests verify the exact
passing depth and prove that one word less fails for slower scenarios.

## Production gates

Before this model may justify Memories support, all of these must become true:

1. Implement a real fourth SDRAM client with bounded/fair arbitration.
2. Prove `B` including emergency refresh, competing clients, request capture,
   read CAS/data timing, and CDC—not only nominal SDRAM latency.
3. Implement the chosen FIFO/cache depth and prove full/empty handling,
   sequential address mapping, initial prefill, setup margin, and reset/abort.
4. Prove the wrapper never receives `bridge_rd` when the required word is
   absent; BRIDGE cannot be stalled or retried.
5. Repeat the proof for the final envelope size and header/payload mux.
6. Pass Quartus fit/timing and adversarial Pocket hardware captures at the
   fastest observed A0 copy cadence.

Until then, the safe answer is not “a large enough FIFO”; it is “service is
unbounded, so Memories remains disabled.”
