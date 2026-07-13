# Swan Song — WonderSwan for Analogue Pocket

Swan Song is an incremental, simulation-first fork of the WonderSwan openFPGA
core. The current branch starts from the released Pocket source while adding a
reproducible build, an executable Verilator regression harness, and a documented
boundary between console logic and Pocket integration. Hardware equivalence has
not yet been confirmed; see [PHASE_STATUS.md](PHASE_STATUS.md).

Start with [BUILDING.md](BUILDING.md), [ARCHITECTURE.md](ARCHITECTURE.md), and
[PHASE_STATUS.md](PHASE_STATUS.md). No BIOS or commercial cartridge image is
included or downloaded.

The WonderSwan system core was developed by [Robert Peip](https://github.com/RobertPeip)
([Patreon](https://www.patreon.com/FPGAzumSpass)) and the Analogue Pocket port
was created by [Adam Gastineau](https://github.com/agg23). Core icon provided by
[spiritualized1997](https://github.com/spiritualized1997). Upstream provenance and
pinned revisions are documented in [UPSTREAMS.md](UPSTREAMS.md).

Report issues with the exact core commit and whether they reproduce in the
MiSTer core. Keep Pocket integration reports here; shared console-logic fixes
should be upstreamed after they are verified.

## Installation

### Easy mode

The updater tools by [@mattpannella](https://github.com/mattpannella) and [@RetroDriven](https://github.com/RetroDriven) are excellent for published openFPGA cores. The current Swan Song development branch is not yet a verified updater release; using an updater today may install or restore upstream WonderSwan 1.0.1 instead. Use this route only after a Swan Song release is explicitly listed.

### Manual mode
When a verified Swan Song release is available, download its APF ZIP from the
Releases page. The current development branch has not been validated on Pocket.

To install the core, copy the `Assets`, `Cores`, and `Platforms` folders over to
the root of your SD card. Please note that Finder on macOS automatically
_replaces_ folders, rather than merging them like Windows does, so you have to
manually merge the folders.

## Usage

ROMs should be placed in `/Assets/wonderswan/common/`.

You must provide the BIOS files for both the original and WonderSwan Color. The
BIOSes should be named `bw.rom` and `color.rom`, and should be placed in
`/Assets/wonderswan/common/`. Both are required data slots, so Pocket can ask
for a missing file before launch; APF also checks their exact sizes. A BIOS
chosen in that browser is remembered for the next launch and is cleared by
Pocket's Reset All to Defaults action.

WonderSwan

* `bw.rom`
* MD5: 54B915694731CC22E07D3FB8A00EE2DB

WonderSwan Color

* `color.rom`
* MD5: 880893BD5A7D53FFF826BD76A83D566E

### Supported Pocket boundary

Swan Song currently supports the openFPGA asset-launch path: Pocket loads a
`.ws` or `.wsc` image plus both user-supplied BIOS files from the SD card, then
provides its APF video, audio, input, save, menu, and Dock transport. This is
not Pocket's first-party physical-cartridge or Library launch path. Cartridge
power remains off, the cartridge and link ports are not used, and no firmware
or game image is bundled.

The selectable hardware models are Auto, WonderSwan, and WonderSwan Color.
PocketChallenge v2 is not advertised: the core does not implement that
machine's pinstrap boot, distinct keypad matrix, absent internal EEPROM, or
native `.pc2` asset path. Renaming a `.pc2` file does not make this a supported
configuration.

### Supported file sizes

The development RTL applies the Pocket data-slot contract before accepting a
file. Cartridge ROMs must be a power of two from 64 KiB through **16 MiB**;
`bw.rom` must be exactly 4 KiB and `color.rom` exactly 8 KiB. The 16 MiB ROM
ceiling is an implemented limit of this core's 24-bit mapper, not a claim about
every possible WonderSwan cartridge. The documented header values reach
16 MiB, while the later Bandai 2003 mapper's six 1 MiB linear-bank bits imply a
theoretical 64 MiB address capacity. Larger images are not supported here. See
the [WSdev ROM-header](https://ws.nesdev.org/wiki/ROM_header) and
[mapper](https://ws.nesdev.org/wiki/Mapper) references and the
[Wonderful WonderSwan target documentation](https://wonderful.asie.pl/docs/target/wswan/).

Save slot 11 uses the cartridge footer to publish and validate the exact
payload size. SRAM types `01/02`, `03`, `04`, and `05` use 32, 128, 256, and
512 KiB. EEPROM types `10`, `20`, and `50` use 128, 2,048, and 1,024 bytes.
Cartridges with RTC add an exact 12-byte trailer. Old 8,204-byte type-`01`
saves must be converted; old 2,060-byte type-`10`/`50` RTC saves are accepted
for compatibility but are written back at their canonical 140/1,036-byte
sizes. The non-destructive conversion commands are in
[BUILDING.md](BUILDING.md#migrating-legacy-type-01-pocket-saves).

At the source level, startup now follows Analogue's documented lifecycle:
Setup remains active through `008F` data-slot completion, delivered `0090` RTC
data, save metadata/table publication, and initialization; the core then
requests `0140`, waits for Pocket's acknowledgement, enters Idle, and does not
enter Running until `0011`; starting a new title invalidates any preceding
title's `0140` acknowledgement. On shutdown, save reads return `2` until Reset
Enter has stopped execution and a fixed 31-`clk_74a` drain guard has elapsed.
Slot requests use the full 48-bit `0082` length and return the documented `0`
ready / `1` never / `2` later results. This is covered by focused simulation;
it is not a claim of physical Pocket validation. The
controlling specifications are Analogue's [boot process](https://www.analogue.co/developer/docs/core-boot-process),
[host/target commands](https://www.analogue.co/developer/docs/host-target-commands),
[`data.json`](https://www.analogue.co/developer/docs/core-definition-files/data-json),
[`core.json`](https://www.analogue.co/developer/docs/core-definition-files/core-json),
and [bus communication](https://www.analogue.co/developer/docs/bus-communication)
documentation.

## Features

### Save States/Sleep + Wake

Memories and Sleep + Wake are disabled in this development tree. The APF
command handler is covered in focused simulation, but the complete state
controller and physical Pocket lifecycle have not passed the release gate yet.

### Fast Forward

Hold the `-` button (default) to run the WonderSwan at 2.5x speed. Tapping the button will lock fast forward on, and it will continue fast forwarding until the button is pressed again.

### Controls

The WonderSwan has a lot of buttons for a handheld in an unusual layout. The default button mappings for the Pocket are as close as I can get to the original control layout.

The running console's own orientation signal selects the native WonderSwan
button matrix shown below. The `Display Orientation` menu changes only how the
finished frame is presented by Pocket's scaler; forcing it does not override
the game's native orientation or remap controls. This separation keeps
game-visible input behavior tied to the emulated hardware.

<table>
<tr>
  <th>Horizontal</th>
  <th>Vertical</th>
</tr>
<tr><td>

| Pocket  | WonderSwan |
|---------|------------|
| D-pad   | X buttons  |
| A       | A          |
| B       | B          |
| X       | Y3         |
| Y       | Y4         |
| L. Trig | Y1         |
| R. Trig | Y2         |
| +       | Start      |
| -       |Fast Forward|

</td><td>

| Pocket  | WonderSwan |
|---------|------------|
| D-pad   | Y buttons  |
| A       | X3         |
| B       | X4         |
| X       | X2         |
| Y       | X1         |
| L. Trig | A          |
| R. Trig | B          |
| +       | Start      |
| -       |Fast Forward|

</td></tr></table>

### System Settings

* `System Type` - Select Auto, WonderSwan, or WonderSwan Color. Changing this option requires resetting the core.
* `CPU Turbo` - Allows the CPU to perform additional processing per frame, which can be used to eliminate some slowdowns.

### Video Settings

The WonderSwan has a native refresh rate of 75.4Hz, but the Analogue Pocket doesn't support higher than ~62Hz (and 60Hz on the Dock). This core provides the option to either run the display directly at 60Hz, introducing tearing, or to buffer complete frames at 60Hz, introducing latency and skipping some frames entirely. The buffered path uses five physical banks so the writer, a pending frame, and up to three immutable display/blend frames never alias.

* `Triple Buffer` - Present only complete frames to prevent producer/scanout tearing. This increases latency and drops producer frames when necessary.
* `Flickerblend` - Blend the newest two or three immutable completed frames with exact rounded RGB levels. History is re-primed after a title/reset, and this option enables buffering implicitly.
* `Display Orientation` - Select the scaler presentation independently of the emulated console's native input orientation.
* `Landscape 180°` - Select the 180-degree landscape presentation. This is not a horizontal mirror or control remap.

### Sound Settings

* `Audio in Fast Forward` - If enabled, play sound when fast forward is active.
