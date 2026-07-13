# Savestate v2 integrity primitive

Status: **isolated and not integrated.**

`src/fpga/core/apf_crc64_ecma32.sv` is the first independently tested building
block for a future version-2 SWAN compatibility envelope. It is deliberately
absent from `src/fpga/ap_core.qsf` and is not instantiated by
`apf_savestate_envelope.sv`, `apf_savestate_staging.sv`, `core_top.v`, or the
live state controller. Version 1 remains the only implemented envelope, and
Memories plus Sleep + Wake remain disabled.

The primitive implements the direct, unreflected CRC-64/ECMA-182 parameters:

- polynomial `0x42f0e1eba9ea3693`
- initial value zero
- final XOR zero
- check value for `123456789`: `0x6c40df5f0b497347`

Its input is a normalized 32-bit blob word. The byte at the lowest blob offset
is in bits `[31:24]`; `byte_count` consumes a contiguous 0-to-4-byte prefix.
The zero-to-four-byte contract supports partial final words without adding
implicit padding. Synchronous `clear` has priority over `enable`, asynchronous
active-low reset and clear both seed zero, and disabled cycles hold. Out-of-
contract `byte_count` values 5 through 7 also hold in synthesis and report a
warning in simulation rather than aliasing to four accepted bytes. Since the ECMA
final XOR is zero, the accumulator output is the final value immediately after
the last accepted clock edge.

The dedicated regression uses an independent bit-at-a-time Python reference.
It covers every possible two-byte string, all single-byte values, the published
`123456789` check in several segmentations, unused-byte poison, enable gaps,
invalid-count rejection, clear priority, asynchronous reset, and 256 deterministic randomized messages
split into arbitrary one-to-four-byte transactions.

No compatibility claim follows from this primitive alone. A production v2
envelope still requires title and BIOS identity capture, a frozen field layout,
durable SDRAM readback checks, complete CDC/backend integration, format failure
gates, Quartus timing/fit evidence, and Pocket hardware validation.
