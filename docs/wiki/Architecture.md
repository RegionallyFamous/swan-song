# Architecture

Swan Song keeps the WonderSwan machine, Pocket integration, and verification
tooling visibly separated. That makes upstream comparison possible and keeps a
Pocket-specific feature from silently redefining console behavior.

## Runtime layers

```text
Analogue Pocket / APF host
        │
        ▼
apf_top + core_top
  commands, data slots, settings, controls, saves, RTC, hardware pins
        │
        ▼
wonderswan.sv
  clocks, SDRAM, frame delivery, presentation, Pocket adaptation
        │
        ▼
SwanTop and VHDL console hierarchy
  CPU, memory map, DMA, interrupts, GPU, sprites, joypad, sound, RTC
```

`apf_top` is the framework boundary. `core_top` owns Pocket lifecycle and data
contracts. `wonderswan.sv` adapts the console to Pocket memory, settings,
controls, and output timing. `rtl/SwanTop.vhd` and the hierarchy below it are
the emulated machine.

The complete source-level module tree is in [the architecture
map](https://github.com/RegionallyFamous/swansong-core/blob/main/ARCHITECTURE.md).

## Clock and reset ownership

The APF bridge runs from Pocket's 74.25 MHz clock. The generated core domains
run the console, memory, and 6.144 MHz RGB delivery. Data crossing those
domains uses explicit synchronizers, acknowledged bundled-data transfers, or
owned loader/unloader paths. Reset/title changes invalidate data that cannot
safely survive a new execution epoch.

The timing constraints analyze related video transfers while separating truly
asynchronous clock groups. Source-level crossing tests reduce risk, but only
the accepted Quartus report can establish the fitted hardware result.

## Cartridge, Open IPL, and persistent data

APF data slots load cartridge ROM, cartridge save data, and two fixed console
EEPROM images. Mono and Color clean-room Open IPL images are immutable FPGA
ROMs selected from the cartridge footer; no external firmware slot exists. The
footer also determines model, mapper, exact cartridge save size, and optional
RTC trailer. Console EEPROM is separately banked so mono and Color owner data
remain resident without aliasing cartridge EEPROM.

The loader keeps the historical direct route for power-of-two ROMs. Compact
whole-bank ROMs are validated, prefixed with `0xff`, and right-aligned into
their mapper aperture before execution. Malformed length, direction, footer,
checksum, or lifecycle requests fail closed.

Detailed addresses and lifecycle rules are in [BUILDING.md](https://github.com/RegionallyFamous/swansong-core/blob/main/BUILDING.md#pocket-lifecycle-and-data-slot-policy).

## Video delivery

The native WonderSwan producer runs near 75.47 Hz, above APF's accepted output
range. Swan Song delivers a 397×258 raster at approximately 59.985 Hz while
keeping the machine itself at native cadence.

Direct mode reads the live frame and may tear. Buffered or temporal-response
modes use five physical frame banks so the writer, pending complete frame, and
up to three immutable scanout/history frames cannot alias. New frames may
supersede only pending work, never a frame visible to scanout.

See [frame delivery](https://github.com/RegionallyFamous/swansong-core/blob/main/FRAME_DELIVERY.md),
[vertical play](https://github.com/RegionallyFamous/swansong-core/blob/main/VERTICAL_PLAY.md),
and [screen authenticity](https://github.com/RegionallyFamous/swansong-core/blob/main/SCREEN_AUTHENTICITY.md).

## Audio and controls

The Pocket wrapper transports signed stereo I²S at 48 kHz. Fast Forward changes
console clock-enable cadence rather than the FPGA clock and may optionally mute
audio. The live console orientation chooses the WonderSwan input matrix;
Pocket scaler orientation changes presentation only.

Only normalized Player 1 digital controls enter gameplay. Device type is
checked before the button word is consumed, so keyboard, mouse, absent, and
reserved packets fail to all-buttons-released. See the [input and Dock
contract](https://github.com/RegionallyFamous/swansong-core/blob/main/FIRST_CLASS_INPUT_DOCK.md).

## Memories boundary

Memories and Sleep/Wake are disabled. The project has a frozen v2 blob
allocation and header field layout, exact RTC/EEPROM device schemas, integrity primitives,
a fail-closed channel ownership mux, isolated SDRAM
reader/writer work, and a bounded EEPROM load-settle ownership guard that keeps
raw device acknowledgements honest. It still does not have the complete
cooperative pause, quiescence, lossless crossing, and atomic live restore
required for production.

The design and remaining gates are recorded in [save-state format](https://github.com/RegionallyFamous/swansong-core/blob/main/SAVESTATE_FORMAT.md),
[v2 allocation and device ABI](https://github.com/RegionallyFamous/swansong-core/blob/main/SAVESTATE_V2_FORMAT.md),
and [Memories staging](https://github.com/RegionallyFamous/swansong-core/blob/main/MEMORIES_STAGING.md).
