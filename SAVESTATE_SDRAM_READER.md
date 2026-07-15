# Isolated savestate SDRAM reader and read-ahead cache

Status: **implemented and adversarially tested in isolation; not in the QSF,
not connected to BRIDGE or the live SDRAM controller, and not evidence that
Memories or Sleep + Wake are supported.**

## Source-pinned timing basis

Official Analogue documentation, rechecked 2026-07-13:

- [Bus Communication](https://www.analogue.co/developer/docs/bus-communication)
  defines BRIDGE as a 32-bit bus without arbitration or a target-side wait
  signal. Reads are buffered: after a read strobe, the core may produce
  `bridge_rd_data` later, but it must do so before the next read strobe. This
  is a deadline, not permission for an SDRAM client to stall Pocket.
- [`00A0 Savestate: Start/Query`](https://www.analogue.co/developer/docs/host-target-commands)
  returns the blob address and size only when creation is done. Pocket then
  reads that published address. `00A4` gives Pocket a destination and maximum
  size before Pocket writes a load blob and requests restore.
- The [Core Boot Process](https://www.analogue.co/developer/docs/core-boot-process)
  confirms the ordering: Pocket polls A0 until completion before copying the
  state out, while A4 Request Load occurs only after Pocket's copy-in.

Repository timing was checked against Swan Song's inherited SDRAM controller,
whose last modifying commit is agg23/openfpga-wonderswan
[`1cce8962b8da8e663ac82c0c95c83488e33aa742`](https://github.com/agg23/openfpga-wonderswan/blob/1cce8962b8da8e663ac82c0c95c83488e33aa742/src/fpga/core/rtl/sdram.sv).
It latches a client request on a rising edge, services x16 burst-length-one
accesses, registers read data, and emits one ready pulse with that data. A new
client therefore must issue distinct low/high request pulses and retain each
address while waiting. Emergency refresh has first priority, followed by
fixed channel order 1, 2, and 3. The controller exposes no error signal.

A current maintained-core audit also checked:

- agg23/openfpga-NES master commit
  [`a09c51e2487686a862d5ec660f515c4c2e0301b5`](https://github.com/agg23/openfpga-NES/blob/a09c51e2487686a862d5ec660f515c4c2e0301b5/target/pocket/core_top.v#L390-L395)
  publishes A0/A4 at `0x40000000` and muxes `0x4xxxxxxx` BRIDGE reads to its
  core-specific savestate controller.
- budude2/openfpga-GBC master commit
  [`864253c6c2d902208db387caabb031574cdd8a5e`](https://github.com/budude2/openfpga-GBC/blob/864253c6c2d902208db387caabb031574cdd8a5e/src/core/core_top.sv#L305-L308)
  uses the same fixed published base and its own core-specific RAM path.

Those are useful maintained A0/A4 address-mapping precedents. They do not
remove Swan Song's need for protected staging, durable readback, and explicit
backpressure: Swan's maximum payload is `0x90300` bytes, while its inherited
inbound buffering is far smaller and BRIDGE still provides no wait signal.

## Implemented contract

`src/fpga/core/apf_savestate_sdram_reader.sv` is a memory-clock-domain-only
x16-to-normalized-x32 adapter with one stable output-cache entry. It contains
no clock-domain crossing and no direct BRIDGE logic.

For each accepted payload-relative offset it:

1. Requires four-byte alignment and a complete x32 word inside
   `0x00000000..0x000902ff`.
2. Performs a wide checked addition to protected staging base `0x01100000`.
3. Pulses the low x16 read request and waits for its exact completion.
4. Pulses the adjacent high x16 request and waits independently.
5. Publishes one normalized x32 word only after both halves succeed.
6. Holds its valid flag, offset, and data unchanged until the consumer accepts
   the word. A successor may be accepted on that same turnover edge.

The protected physical byte range is `0x01100000..0x011902ff`, or x16 word
addresses `0x00880000..0x008c817f`. SDRAM values `0x2211` and `0x4433` are
reassembled as normalized blob word `0x11223344`; `read_word[31:24]` is always
the byte at the lowest blob address. No low-half result is ever exposed as a
valid x32 word.

`read_request_ready` is explicit backpressure for a future lossless
coordinator/FIFO. It deasserts during either SDRAM access and while an output
word is unconsumed. `read_word_valid` and `read_word_ready` provide the stable
cache handoff. `fetched_bytes` counts complete physical x32 reads;
`delivered_bytes` counts only consumer handshakes.

`quiescent` is stronger than physical-request idle: it is false while the
one-entry response cache is populated, even though the request state machine
has returned to `IDLE`. This lets the isolated v2 preflight safely abort or
invalidate on title/content change without mistaking a held response for a
drained transaction. A v2 composition must also override `STAGE_BYTES` with
the fixed `0x120000` payload size; the v1-sized default remains an isolated
legacy transport fixture.

Invalid address, either backend error, or abort poisons the transaction and
invalidates the cache. Abort prevents a second half and has priority even when
ready and error arrive on the same edge. If a request is physically
outstanding, the reader stays in a drain state—including while abort remains
asserted—until the stale ready pulse is consumed. A new transaction cannot
mistake that pulse for its own acknowledgement.

## Durable CRC readback

The future save coordinator can prove that SDRAM contains the durable payload
rather than trusting the write stream:

1. Finish and logically commit all `0x90300` payload bytes through the isolated
   writer.
2. Start this reader and submit offsets `0, 4, ... 0x902fc` in order.
3. Feed each `read_word_valid && read_word_ready` word to
   `apf_crc64_ecma32` with `byte_count=4`, while requiring both public byte
   counters to finish at exactly `0x90300`.
4. Compare the readback CRC with the serializer's payload CRC. Any mismatch,
   missing word, abort, range error, or backend failure invalidates the image.
5. Only after that comparison may the coordinator finalize the envelope and
   let the A0 command report `done` with a readable blob pointer.

The same primitive can validate an A4 blob after Pocket's complete copy-in and
before any live restore begins. This prevents a partially written or corrupted
staging image from reaching the emulator state bus.

## A0 BRIDGE read deadline and remaining work

The cache is deliberately stable, but its ready/valid interface cannot itself
backpressure BRIDGE. A future `clk_74a` wrapper must capture the requested A0
blob address on `bridge_rd`, submit the mapped payload offset, copy the returned
word into a dedicated `bridge_rd_data` register, and keep that register stable
for APF. Header words will require the envelope/header mux in front of this
payload reader.

Because Analogue requires the result before the *next* read strobe, production
integration must prove a worst-case service bound including refresh and all
other SDRAM clients. If that bound cannot be guaranteed, the wrapper needs a
deeper sequential prefetch FIFO/cache and bounded arbitration before Memories
can be advertised. Silently dropping a request when `read_request_ready` is
low is forbidden.

Other explicit assumptions and gates:

- `sdram_ready` occurs exactly once for each accepted edge request and returns
  valid `sdram_data` on that pulse. `sdram_error` is meaningful only then; a
  future connection to the current controller would tie it low unless stronger
  monitoring is added.
- Reader, CDC adapter, and SDRAM arbiter must share reset handling whenever a
  physical request is outstanding. Local reset alone cannot identify a late
  physical completion.
- A lossless, full-observed CDC request/response path is still required.
- The future fourth SDRAM client needs bounded arbitration against live ROM,
  save RAM, and bridge traffic. This slice does not edit `sdram.sv`.
- Production full-blob header mapping, A0 publication, composition of the
  isolated A4 preflight with the real reader plus future subsystem semantic
  gates, Quartus fit/timing, and Pocket hardware tests remain unimplemented.

The dedicated Verilator regression covers exact first/last bounds, endian
normalization, independently stalled halves, stable cache data, held-request
backpressure, same-edge pop/push turnover, malformed/misaligned/overflow
offsets, low/high backend failures, cache invalidation, abort before issue,
abort during either half, abort held across multiple clocks, stale-ready drain,
abort/ready/error priority, and 256 randomized reads with independent stalls
and consumer hold times.
