# WonderSwan Memories v2 fixed ABI

Status: **fixed layout, exact RTC/EEPROM controller boundaries, and isolated
atomic-owner/EEPROM-walker slices implemented and focused-tested; none is
integrated into production.** The production core still advertises neither
Memories nor Sleep + Wake. This document,
`src/fpga/core/apf_savestate_v2_layout_pkg.sv`, and
`src/fpga/core/apf_savestate_v2_device_abi_pkg.sv` freeze the target binary
contract. The live RTC and both EEPROM instances expose synthesis-tested
freeze/export/load ports, but every production instance ties those ports off.
The isolated owner and EEPROM walker are not instantiated and are absent from
`ap_core.qsf`; the production top level still sets `savestate_supported` false
and the shipped core descriptor still sets `sleep_supported` false. These
slices prove bounded control- and data-plane contracts only. There is no
complete v2 serializer/validator/reader/writer, global clock-domain integration,
production owner wiring, or change to the version-1 transport.

Version 1 is not a migration source. Its 32-byte envelope and `0x90300` payload
omit CPU pipeline state, live PPU/APU pipelines, RTC protocol/timing, EEPROM
controller/backing state, and mapper/flash state. A v2 loader must reject the
exact v1 tuple before any live-state mutation.

## Byte and integrity conventions

The byte at the lowest normalized APF blob offset occupies bridge word bits
`[31:24]`; structured multibyte scalars are big-endian. Raw IRAM, SRAM, EEPROM,
flash, and ROM-footer arrays are stored one byte per ascending emulated/source
address. No compiler structure, native VHDL enumeration, pointer, uninitialized
RAM, or don't-care bit may enter the image.

Both integrity fields use direct, unreflected CRC-64/ECMA-182: polynomial
`0x42f0e1eba9ea3693`, initial value zero, final XOR zero. The payload CRC covers
all exact `0x120000` payload bytes, including deterministic zero padding. The
header CRC covers bytes `0x00..0xf7` and is stored at `0xf8..0xff`.

## Exact blob and address reservation

| Blob-relative range | Bytes | Owner |
| ---: | ---: | --- |
| `0x000000..0x0000ff` | `0x100` | v2 header |
| `0x000100..0x1200ff` | `0x120000` | fixed payload |
| **Total** | **`0x120100` (1,179,904)** | **294,976 bridge words** |

The APF bridge range is `0x40000000..0x401200ff`. Only the payload needs SDRAM
backing; the header may be captured/synthesized separately. The payload staging
reservation is byte range `0x01100000..0x0121ffff`, x16 word range
`0x00880000..0x0090ffff`. Maximum cartridge SRAM ends at `0x0107ffff`, followed
by the protected `0x01080000..0x010fffff` guard gap.

## Header

| Offset | Size | Meaning |
| ---: | ---: | --- |
| `0x00` | 4 | `0x5357414e` (`SWAN`) |
| `0x04` | 4 | envelope version `2` |
| `0x08` | 4 | header bytes `0x100` |
| `0x0c` | 4 | payload bytes `0x120000` |
| `0x10` | 4 | total bytes `0x120100` |
| `0x14` | 4 | format `0x57530002` |
| `0x18` | 4 | feature flags |
| `0x1c` | 4 | zero |
| `0x20` | 4 | original ROM-file bytes |
| `0x24` | 4 | bytes `{model, mapper, ramtype, active_bios}` |
| `0x28` | 4 | hard settings-match mask, initially `0x400` |
| `0x2c` | 4 | 13-bit settings snapshot; upper 19 bits zero |
| `0x30` | 8 | ROM CRC64 over original source-file bytes |
| `0x38` | 8 | active BIOS CRC64 |
| `0x40` | 8 | mono BIOS CRC64 |
| `0x48` | 8 | Color BIOS CRC64 |
| `0x50` | 8 | capture wall-clock epoch seconds, or zero |
| `0x58` | 8 | CRC64 of the complete fixed payload |
| `0x60` | 4 | active IRAM bytes |
| `0x64` | 4 | active SRAM bytes |
| `0x68` | 4 | active cartridge EEPROM bytes |
| `0x6c` | 4 | active internal EEPROM bytes |
| `0x70` | 4 | active flash-overlay bytes |
| `0x74` | 16 | exact final ROM-footer bytes in source order |
| `0x84` | 16 | `SWANSONG-STATE2\0` ABI identity |
| `0x94` | 4 | CPU schema `1` |
| `0x98` | 4 | PPU schema `1` |
| `0x9c` | 4 | APU schema `1` |
| `0xa0` | 4 | device/controller schema `1` |
| `0xa4` | 4 | canonical capture policy `1` |
| `0xa8` | 4 | RTC policy: `0` exact, `1` elapsed-time advance |
| `0xac..0xf7` | 76 | zero |
| `0xf8` | 8 | header CRC64 |

Feature bits are: SRAM `0`, cartridge EEPROM `1`, cartridge RTC `2`, flash
overlay `3`, effective Color model `4`, and valid wall clock `5`. All other
bits are zero. SRAM and cartridge EEPROM are mutually exclusive; flash requires
the Bandai 2003 mapper; the cartridge RTC flag must exactly match that mapper;
wall-clock validity requires RTC; model, Color flag, and active BIOS must agree.
The SRAM/EEPROM feature must exactly match the footer RAM type, and header
active-length fields must exactly match that RAM type and model; the loader does
not trust arbitrary shorter lengths.

ROM identity is CRC64 plus exact original file length and all 16 footer bytes,
before compact-ROM right alignment or `0xff` fill. Effective model, mapper, RAM
type, active BIOS CRC, and CPU-turbo setting are hard matches. The inactive BIOS
CRC is diagnostic. Presentation and input-layout settings use the current
Pocket value after restore. The 13-bit settings snapshot is `{system[1:0],
cpu_turbo, triple_buffer, flicker[1:0], orientation[1:0],
control_layout[1:0], horizontal_flip, color_profile, fast_forward_audio}`; its
initial hard-match mask is only CPU turbo (`0x400`).

## Fixed payload map

| Payload range | Bytes | Contents |
| ---: | ---: | --- |
| `0x000000..0x003fff` | 16 KiB | CPU and machine/device state |
| `0x004000..0x007fff` | 16 KiB | PPU state |
| `0x008000..0x00bfff` | 16 KiB | APU state |
| `0x00c000..0x00cfff` | 4 KiB | canonical live I/O image |
| `0x00d000..0x00dfff` | 4 KiB | internal EEPROM backing |
| `0x00e000..0x00e7ff` | 2 KiB | cartridge EEPROM backing |
| `0x00e800..0x00ffff` | 6 KiB | zero reserve |
| `0x010000..0x01ffff` | 64 KiB | IRAM |
| `0x020000..0x09ffff` | 512 KiB | cartridge SRAM |
| `0x0a0000..0x11ffff` | 512 KiB | mutable flash overlay |

### Machine state

| Range | Bytes | Contents |
| ---: | ---: | --- |
| `0x000000..0x0000ff` | `0x100` | directory and capture invariants |
| `0x000100..0x0003ff` | `0x300` | CPU registers, HALT, prefetch and pipeline |
| `0x000400..0x0004ff` | `0x100` | IRQ, keypad and serial |
| `0x000500..0x0006ff` | `0x200` | GDMA and SDMA |
| `0x000700..0x0007ff` | `0x100` | semantic scheduler/divider phase |
| `0x000800..0x0008ff` | `0x100` | mapper, cartridge and flash controller |
| `0x000900..0x0009ff` | `0x100` | RTC |
| `0x000a00..0x000aff` | `0x100` | internal EEPROM controller |
| `0x000b00..0x000bff` | `0x100` | cartridge EEPROM controller |
| `0x000c00..0x003fff` | `0x3400` | zero reserve |

## Implemented device-controller schemas

The following schema is executable in the device ABI package and byte-for-byte
matched by focused tests against the real VHDL ports. It defines the active
prefix of each fixed `0x100`-byte section; every remaining byte is zero.

### RTC (`payload + 0x000900`)

| Section offset | Bytes | Contents |
| ---: | ---: | --- |
| `0x00` | 1 | command latch |
| `0x01` | 1 | read latch |
| `0x02` | 1 | index in bits `2:0`; upper bits zero |
| `0x03` | 1 | bits `0..4`: register-write history, register-read history, `0090` edge history, change latch, saved-time edge history |
| `0x04` | 4 | live epoch seconds, u32 big-endian |
| `0x08` | 4 | pending elapsed-time catch-up seconds, u32 big-endian |
| `0x0c` | 4 | 36.864 MHz subsecond phase, u32 big-endian, maximum `36,863,999` |
| `0x10..0x16` | 7 | live year/month/day/weekday/hour/minute/second signal values |
| `0x17..0x1d` | 7 | buffered year/month/day/weekday/hour/minute/second signal values |
| `0x1e..0xff` | 226 | zero |

Calendar bytes preserve the implemented signal widths: year 8, month 5, day
6, weekday 3, hour 6, and minute/second 7 bits. Exact restore deliberately
accepts non-BCD values within those widths. Software command `0x14` can write
them, and the translated RTC's multi-edge normalization legitimately exposes
transients such as `0x59 -> 0x5a -> 0x60`. A semantic BCD/calendar helper exists
for diagnostics, but it is not a load gate. Index `7`, unknown flags, excessive
subsecond phase, nonzero upper field bits, and all padding still fail closed.

### EEPROM controller (`payload + 0x000a00` and `+ 0x000b00`)

| Section offset | Normalized 32-bit word |
| ---: | --- |
| `0x00` | `{WriteData[15:0], ReadData[15:0]}` |
| `0x04` | `{Addr[15:0], Cmd[7:0], FSM[2:0], writeEnable, writeProtect, readDone, 2'b0}` |
| `0x08` | `{readDelay[3:0], sizeWords[10:0], clearCounter[10:0], 6'b0}` |
| `0x0c` | `{addrCounter[10:0], writeValue[15:0], ssLoaded, RAMWrEn, written, 2'b0}` |
| `0x10..0xff` | zero |

Stable FSM codes are `0` OFF, `1` IDLE, `2` EVALCMD, `3` CLEAR, `4` OVERWRITE,
`5` WRITEWAIT, `6` READWAIT, and `7` READONE. The VHDL port uses a convenient
native 128-bit packing, while the executable adapter above emits semantic
big-endian fields, consistent with the rest of v2. At an acknowledged capture,
pending RAM writes have committed exactly once and both `ssLoaded` and
`RAMWrEn` are required zero; `written` remains the exact outgoing pulse
history. The validator also binds controller size and reachable counter/FSM
relationships to model and footer RAM type. Restoring register latches does not
synthesize CPU write strobes, and a synchronous-RAM settle edge occurs before
resume.

### PPU state

| Range | Bytes | Contents |
| ---: | ---: | --- |
| `0x004000..0x0043ff` | `0x400` | registers, timing, timers, line latches |
| `0x004400..0x004bff` | `0x800` | both background fetch engines/shifters |
| `0x004c00..0x0053ff` | `0x800` | sprite DMA and line-fetch pipeline |
| `0x005400..0x0055ff` | `0x200` | exact 512-byte sprite RAM |
| `0x005600..0x005dff` | `0x800` | current/next decoded sprite caches |
| `0x005e00..0x0061ff` | `0x400` | palettes, grayscale/DAC, output pipeline |
| `0x006200..0x007fff` | `0x1e00` | zero reserve |

### APU state

| Range | Bytes | Contents |
| ---: | ---: | --- |
| `0x008000..0x0083ff` | `0x400` | global registers, mixer, arbitration/timing |
| `0x008400..0x0087ff` | `0x400` | channel 1 |
| `0x008800..0x008bff` | `0x400` | channel 2 |
| `0x008c00..0x008fff` | `0x400` | channel 3 and sweep |
| `0x009000..0x0093ff` | `0x400` | channel 4, noise and LFSR |
| `0x009400..0x0097ff` | `0x400` | Hyper Voice/channel 5 |
| `0x009800..0x009bff` | `0x400` | SDMA/APU interface latches |
| `0x009c00..0x00bfff` | `0x2400` | zero reserve |

## Memory and padding rules

The first 256 I/O bytes are a side-effect-free canonical live-register image;
the remaining `0xf00` bytes are zero. Restore must not replay ordinary software
write strobes.

Internal EEPROM is canonicalized as Color bytes at `0x00d000..0x00d7ff` and
mono bytes at `0x00d800..0x00d87f`. Only the active model slice is captured and
applied; the inactive slice and `0x00d880..0x00dfff` are zero. Header field
`0x6c` is therefore the active length, exactly 2,048 for Color or 128 for mono,
not the 4 KiB section allocation. Restoring one model must leave the other
resident model bank unchanged. Cartridge EEPROM
uses the first 128, 2,048, or 1,024 bytes for footer types `0x10`, `0x20`, or
`0x50`; its remaining bytes are zero.

Mono uses the first 16 KiB of IRAM and zeros the upper 48 KiB. Color uses all
64 KiB. SRAM footer types `0x01/0x02`, `0x03`, `0x04`, and `0x05` use 32, 128,
256, and 512 KiB respectively; the tail is zero. The complete flash region is
zero unless the flash feature is valid, in which case exactly 512 KiB is active.
Flash state remains forbidden until a bounded MBM29DL400 controller exists.

All structural reserve ranges, inactive memory tails, undefined register bits,
and unused scalar bits must be written as zero and rejected if nonzero on load.
The package's `v2_fixed_zero_payload_byte` and
`v2_fixed_zero_header_byte` helpers identify bytes that are zero for every v2
image; model/title-dependent zero tails are additional validation.

## Isolated owner and EEPROM walker

`apf_savestate_v2_owner.sv` and `apf_savestate_v2_eeprom_walker.sv` are
deliberately isolated verification slices. Neither is in `ap_core.qsf`, neither
is instantiated by the production core, and no current Pocket command reaches
either module.

### Atomic owner ordering and failure boundary

The owner admits one operation at a time. Restore additionally requires a valid
staged image. It locks staged-image replacement for the complete transaction,
snapshots the image generation when accepting restore, and checks that
generation through application. A generation change before the irreversible
restore-apply pulse is a recoverable rejection; the same change at or after
that pulse is fatal.

The acquisition order is fixed:

1. Request the runtime pause and wait for an instruction/HALT-boundary
   acknowledgement.
2. Assert device freeze, then remain in the same acquisition state until all
   device acknowledgements and global SDRAM quiescence are both observed; the
   two acknowledgements are not ordered relative to each other.
3. Acquire staging ownership and wait for its data plane to be idle.
4. Issue exactly one capture-start or restore-apply pulse.

Global SDRAM quiescence is an acquisition condition, not a condition imposed on
legitimate staging traffic or refresh after ownership transfers. A terminal
result is not released until the independent staging data plane is quiescent.
Release is the reverse ownership order: staging, devices, then runtime; the
owner publishes the result only after the runtime pause acknowledgement falls.
Stale terminals, wrong-operation terminals, and late same-edge failures fail
closed, while cancellation drains any request already in flight.

A capture abort is recoverable only while the owner can prove that no live
mutation or ambiguous outstanding ownership remains. Restore error, cancel,
timeout, or generation loss at or after the apply barrier asserts a sticky
fatal-reset hold. An unprovable capture drain/release failure does the same.
Fatal hold preserves the runtime/device freeze boundary and is cleared only by
the lifecycle reset. `MAX_PHASE_CYCLES=1` is intentionally unusable as a
production timeout; integration must supply a derived bound.

### EEPROM backing-memory walker

The walker maps the physical x16 EEPROM RAMs into normalized v2 bytes: internal
Color words `0..1023`, internal mono words `1024..1087`, and cartridge words
`0..1023`. Capture emits each complete fixed section, including deterministic
zeroes for inactive banks, inactive cartridge bytes, and padding.

Restore is a strict two-pass operation. The first pass reads and validates the
entire fixed section, including zero padding, without issuing a backing-memory
write. Only after that succeeds does the second pass reread the image and apply
active words. The external owner must keep staging immutable across both
passes. Staging and backing-memory requests are one-cycle edge pulses, and an
abort drains every acknowledged outstanding request before normal ownership can
be released.

A timeout enters poison because a late completion can no longer be attributed
safely. The walker records when a restore write may have committed and when a
successful write was acknowledged; any restore failure after a possible write
is also poison. Poison rejects restart, retains `ownership_retained` and
`frozen_ack`, and ignores late completions as results until lifecycle reset.
This proves the EEPROM-section traversal and failure boundary, not the
production SDRAM mux, complete payload transport, or global rollback policy.

## Atomicity and rejection

A0 must freeze at a CPU instruction/HALT boundary, drain DMA and SDRAM, stop
all emulated clocks on one edge, build the payload, and read it back while
computing CRC before publishing success. PPU/APU live pipelines are serialized;
physical bridge FIFOs, SDRAM refresh/arbitration history, frame-history filters,
I2S serialization phase, and debug counters are flushed and re-primed instead.

The RTC and EEPROM device-local pieces of that protocol now exist. A load is
ignored until a prior-cycle freeze acknowledgement; an acknowledged export is
stable across bus writes and bus resets. EEPROM freeze drains its pending RAM
write, consumes both effects of any pending legacy EEPROM-register load, and
makes stale hidden legacy state irrelevant to future reset behavior. The
isolated owner and walker exercise those boundaries, but the production
pause/drain integration, complete payload writer/reader, lossless clock-domain
crossings, and all-live-state rollback policy remain open.

Pocket's `0090` event seeds time once at boot; it is not a continuously updated
host clock. V2 therefore maintains a live epoch from that seed and the RTC
second tick. RTC policy `1` is an explicit Swan Song rule: preserve the saved
protocol command, read latch, index, edge history, subsecond count, and buffered
calendar, then advance only the live calendar/timestamp by
`max(0, current_epoch - capture_epoch)`. Set the RTC change latch before release.
If elapsed-time arithmetic overflows the supported counter or catch-up cannot
complete while the machine is frozen, restoration fails closed; it must never
run the game while applying one second per MHz clock. With no valid epoch,
policy `0` performs an exact restore.

A4 writes only isolated staging storage. Before any live mutation it validates
the exact length/order, both CRCs, ABI/schema/policies, ROM/model/mapper/RAM/BIOS
identity, hard settings, active sizes, every enum/flag, and all zero padding.
Failure before mutation resumes the original state. Failure after application
begins holds the console reset until a clean title reload. Reset Enter, PLL loss,
title reload, interruption, or a new offset-zero transaction invalidates a
previous staged image.

The exact v1 tuple (`version=1`, header `0x20`, payload `0x90300`, total
`0x90320`, format `0x57530001`) and every partial mixture of v1/v2 static fields
must fail the v2 static gate. Future field meaning, capture-cut, or restore
semantic changes require a new format/ABI; compatible Git builds need not match
build IDs.

## Focused executable contract

Run:

```sh
./sim/rtl/run_apf_savestate_v2_layout_tb.sh
./sim/rtl/run_apf_savestate_v2_device_abi_tb.sh
./sim/rtl/run_rtc_state_tb.sh
./sim/rtl/run_eeprom_state_tb.sh
./sim/rtl/run_apf_savestate_v2_eeprom_walker_tb.sh
./sim/rtl/run_apf_savestate_v2_owner_tb.sh
```

The layout test checks every region boundary and sum, header compound-field
boundary, exact address reservation, schema/feature identity, RAM-size table,
v1 rejection, and fixed-zero byte count. The device ABI adds exhaustive masks,
native/payload adapters, controller reachability, all 65,536 EEPROM word values,
and exact backing byte order. The GHDL tests exercise the real RTC/EEPROM RTL,
including synthesis, transient RTC replay, all EEPROM FSMs, pending-write drain,
legacy-state normalization, reset ordering, and synchronous-read settling. The
walker test covers both EEPROM layouts, two-pass restore, padding rejection,
late staging/backing-memory completions, restart rejection, and ownership held
through poison. The owner test covers acquisition/release ordering, generation
locking, stale and wrong-operation terminals, legal non-quiescent staging
traffic, recoverable pre-apply aborts, sticky fatal restore, lifecycle reset,
and phase timeouts.

All six behavior tests are part of `make regression`. The owner and walker
runners skip Yosys by default even when it is installed; setting
`SWAN_REQUIRE_YOSYS=1` makes synthesis mandatory, including tool availability
and a nonempty netlist. Only `0` and `1` are accepted. Passing these isolated
tests is not evidence of Quartus fit, production integration, or Pocket
hardware behavior; both modules remain outside the Quartus project.
