# Swan Song save-state format foundation

Status: **format contract implemented and tested; Memories and Sleep + Wake
remain disabled.**

Analogue's documented runtime order is decisive here. For `00A0`, Pocket polls
until the core says the complete blob is ready and only then copies it out. For
`00A4`, Pocket copies the complete blob into the core before issuing Request
Load. See [Core Boot Process](https://www.analogue.co/developer/docs/core-boot-process)
and [Host/Target Commands](https://www.analogue.co/developer/docs/host-target-commands).
The inherited FIFO streamer does not satisfy that random-access staging
contract, so `savestate_supported` and `sleep_supported` deliberately remain
false.

## Version 1 compatibility envelope

`apf_savestate_envelope.sv` defines eight 32-bit APF bridge words at these
byte-addressed offsets. This specifies bridge-visible word values only; it does
not assume undocumented SD-card byte serialization.

| Offset | 32-bit value | Meaning |
| ---: | ---: | --- |
| `0x00` | `0x5357414e` | `SWAN` magic word |
| `0x04` | `0x00000001` | Envelope version 1 |
| `0x08` | `0x00000020` | Header length: 32 bytes |
| `0x0c` | `0x00090300` | MiSTer payload length: 590,592 bytes |
| `0x10` | `0x00090320` | Exact total blob length: 590,624 bytes |
| `0x14` | `0x57530001` | WonderSwan payload-format revision 1 |
| `0x18` | `0x00000000` | Compatibility flags; none defined in v1 |
| `0x1c` | `0x00000000` | Reserved; must be zero |

The validator accepts only aligned, strictly sequential words beginning at
offset zero. Magic, version, both lengths, format ID, flags, and reserved data
must match. Request Load finalization rejects missing, short, long, duplicate,
misaligned, gapped, reordered, or post-error data before it can be considered
compatible. A new valid magic word explicitly begins a fresh transfer.

Any change to the MiSTer payload's field meaning, field ordering, included
state, memory layout, or restore semantics requires a new payload-format
revision. A change to the envelope interpretation requires a new envelope
version. Older blobs must never be guessed into a newer format.

## Payload-size proof

The maximum is derived from the checked-in `savestates.vhd`, not the old Pocket
constant:

| MiSTer payload section | Bytes |
| --- | ---: |
| Two 32-bit header words | 8 |
| 63 internal 64-bit state words | 504 |
| Register memory | 256 |
| System RAM | 65,536 |
| Maximum cartridge SRAM (`ramtype = 0x05`) | 524,288 |
| **Total** | **590,592 (`0x90300`)** |

The previous `0x90200` value was 256 bytes short. A focused source contract now
re-derives this maximum from the MiSTer constants and locks Pocket's future
query size to payload plus the 32-byte envelope: `0x90320`.

## What remains before Memories can be enabled

The new module is intentionally not connected to `save_state_controller.sv`.
Its payload output is an interface for a future full-size staging-memory writer,
not a live-state streaming interface.

The inherited load FIFO holds 4,096 32-bit words (16 KiB), and its save FIFO
holds four 64-bit words (32 bytes). That is incompatible with APF's complete
blob ordering and the 590,624-byte envelope. A certifiable implementation still
needs:

1. Full random-access staging storage with bounds, completion, and overwrite
   protection for the exact blob length.
2. A0 generation that finishes the complete staged image before reporting
   result `2`, including deterministic padding for smaller cartridge-RAM types.
3. A4 validation of the complete envelope before asserting MiSTer `ss_load`;
   malformed input must leave all emulated state untouched.
4. Title compatibility binding, interruption/reset behavior, repeated
   save/load, and older-format rejection tests through the compiled wrapper.
5. Pocket/Dock hardware validation across mono/Color, every RAM type,
   EEPROM/RTC, audio activity, fast-forward, both orientations, and repeated
   Sleep + Wake cycles.

Until those gates pass, unsupported A0/A4 requests are rejected in the command
handler without reaching the legacy controller.
