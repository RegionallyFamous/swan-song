# Swan Song save-state format foundation

Status: **format contract implemented and tested; Memories and Sleep + Wake
remain disabled.**

## Production completeness audit

Version 1 is a transport/envelope experiment, not a complete WonderSwan machine
state and must never be enabled as Pocket Memories. A July 2026 RTL audit found
that the inherited MiSTer payload varies with cartridge RAM type and omits CPU
prefetch/interrupt-inhibit state, external and internal EEPROM backing,
RTC protocol/time phase, substantial PPU fetch/sprite phase, and substantial
APU phase. HALT is now preserved in the legacy-zero FLAGS bit 3 and the
save-idle predicate accepts a halted CPU while still rejecting a pending IRQ,
so an A0 request cannot wait forever solely because a title executed `HLT`.

Production therefore requires a new fixed-size payload-format revision, exact
zero padding for every unused region, complete mutable-state coverage, and
wrong-title/model/BIOS/settings plus payload-integrity rejection before any live
mutation. Loading a version-1 experiment as that future format is forbidden;
the version/format gate must reject it explicitly. The disabled top-level flags
make this the safe time to break format compatibility rather than ship a Memory
that resumes with different CPU, EEPROM, RTC, video, or audio behavior.

The frozen target revision is documented in
[`SAVESTATE_V2_FORMAT.md`](SAVESTATE_V2_FORMAT.md). Its package and exhaustive
layout test define the fixed header, payload regions, title/model identity,
active-size rules, and deterministic padding. Exact synthesis-tested RTC and
internal/cartridge EEPROM controller ports now freeze, export, and restore their
complete local sequential state under an executable device ABI. Production
ties those ports off: they are deliberately not yet connected to a global v2
owner, and EEPROM backing RAM is not yet walked into the payload.

Reference coverage is consistent with this decision: pinned
[ares system serialization](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/system/serialization.cpp#L40-L49)
includes CPU, PPU, APU, system EEPROM, cartridge, IRAM, and serial state, while
its [cartridge serialization](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cartridge/serialization.cpp)
includes SRAM, EEPROM, RTC protocol/timing, and mapper state. Pinned
[Mesen WonderSwan serialization](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsConsole.cpp#L449-L489)
also covers both EEPROM memories/controllers and rejects model mismatch. These
are behavioral references, not byte-layout compatibility targets.

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
3. A4 validation of the complete envelope before asserting any live v2
   state-load/apply signal; malformed input must leave all emulated state
   untouched.
4. Title compatibility binding, interruption/reset behavior, repeated
   save/load, and older-format rejection tests through the compiled wrapper.
5. Pocket/Dock hardware validation across mono/Color, every RAM type,
   EEPROM/RTC, audio activity, fast-forward, both orientations, and repeated
   Sleep + Wake cycles.

The device-local prerequisite is no longer hypothetical: focused GHDL behavior
and synthesis tests prove prior-cycle freeze/load ordering, exact RTC transient
replay, EEPROM pending-write drain, no synthetic MMIO commands, hidden legacy
state normalization, and synchronous-RAM settling. The remaining work is to
coordinate those boundaries with CPU/DMA/PPU/APU/mapper pause, capture the
separate EEPROM backing memories, and transact the complete validated blob.

Until those gates pass, unsupported A0/A4 requests are rejected in the command
handler without reaching the legacy controller.
