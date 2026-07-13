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

I highly recommend the updater tools by [@mattpannella](https://github.com/mattpannella) and [@RetroDriven](https://github.com/RetroDriven). If you're running Windows, use [the RetroDriven GUI](https://github.com/RetroDriven/Pocket_Updater), or if you prefer the CLI, use [the mattpannella tool](https://github.com/mattpannella/pocket_core_autoupdate_net). Either of these will allow you to automatically download and install openFPGA cores onto your Analogue Pocket. Go donate to them if you can

### Manual mode
When a verified Swan Song release is available, download its APF ZIP from the
Releases page. The current development branch has not been validated on Pocket.

To install the core, copy the `Assets`, `Cores`, and `Platforms` folders over to
the root of your SD card. Please note that Finder on macOS automatically
_replaces_ folders, rather than merging them like Windows does, so you have to
manually merge the folders.

## Usage

ROMs should be placed in `/Assets/wonderswan/common/`

You must provide the BIOS files for both the original and WonderSwan Color. The BIOSes should be named `bw.rom` and `color.rom`, and should be placed in `/Assets/wonderswan/common/`.

WonderSwan
* `bw.rom`
* MD5: 54B915694731CC22E07D3FB8A00EE2DB

WonderSwan Color
* `color.rom`
* MD5: 880893BD5A7D53FFF826BD76A83D566E

## Features

### Save States/Sleep + Wake

Memories and Sleep + Wake are disabled in this development tree. The APF
command handler is covered in focused simulation, but the complete state
controller and physical Pocket lifecycle have not passed the release gate yet.

### Fast Forward

Hold the `-` button (default) to run the WonderSwan at 2.5x speed. Tapping the button will lock fast forward on, and it will continue fast forwarding until the button is pressed again.

### Controls

The WonderSwan has a lot of buttons for a handheld in an unusual layout. The default button mappings for the Pocket are as close as I can get to the original control layout.

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

* `System Type` - Choose what type of WonderSwan to boot. Changing this option requires resetting the core
* `CPU Turbo` - Allows the CPU to perform additional processing per frame, which can be used to eliminate some slowdowns.

### Video Settings

The WonderSwan has a native refresh rate of 75.4Hz, but the Analogue Pocket doesn't support higher than ~62Hz (and 60Hz on the Dock). This core provides the option to either run the display directly at 60Hz, introducing tearing, or to triple buffer frames at 60Hz, introducing latency and skipping some frames entirely.

* `Triple Buffer` - Triple buffer image to prevent tearing. Please note that this does increase latency and will cause frames to be dropped.
* `Flickerblend` - Use a combination of 2 or 3 frames of data to perform blending on flickering UI elements. This will decrease the flickering and resolve the flicker into a lighter grey color. Please note that this enables the frame buffer implicitly.
* `Orientation` - Lock the screen rotation to a particular direction. When set to `Auto`, the core will automatically rotate the display.
* `Flip Horizontal` - Flips the display whenever the WonderSwan would display in horizontal mode.

### Sound Settings

* `Fast Forward` - If enabled, play sound when fast forward is active.
