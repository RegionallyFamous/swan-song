# Compatibility and Current Limits

> **Current verdict:** Swan Song is a development project, not a verified
> release. Automated simulation is extensive, but no FPGA build from this fork
> has completed the full physical Pocket and Dock release matrix.

## Intended supported path

Swan Song targets the supported openFPGA asset-launch path:

- `.ws` and `.wsc` images loaded from the Pocket SD card;
- a built-in open IPL with no external BIOS-file requirement;
- `Auto`, `WonderSwan`, and `WonderSwan Color` machine choices;
- Pocket and Dock Player 1 digital controls;
- APF video, 48 kHz audio, settings, cartridge saves, and fixed console EEPROM;
  and
- side-by-side installation under the independent
  `RegionallyFamous.SwanSong` core identity.

The loader accepts whole-64-KiB-bank images from 64 KiB through the core's
implemented 16 MiB mapper limit. Conventional power-of-two files use the
direct path. Compact non-power-of-two files must have a valid final WonderSwan
footer and checksum; Swan Song right-aligns them in the next power-of-two
aperture with the documented `0xff` prefix.

That is an implemented core limit, not a statement that every unusual or
modified image will work.

## Deliberate limits

| Capability | Current status |
| --- | --- |
| Verified public release | Not available |
| Physical Pocket and Dock acceptance | Pending |
| First-party Analogue Library entries | Not exposed by the public APF interface |
| Physical WonderSwan cartridges | Unsupported; cartridge power and bus are not used |
| WonderSwan link port and infrared | Unsupported |
| PocketChallenge v2 / `.pc2` | Unsupported |
| Pocket Memories and Sleep/Wake | Disabled pending a complete safe state path |
| WonderWitch `.fx` applications | Not a normal cartridge path; full Freya/flash environment is not implemented |
| Keyboard, mouse, or multiplayer controls | Unsupported for gameplay |

Swan Song does not patch Pocket firmware, impersonate a first-party core, or
inject guessed Library records. If Analogue publishes a supported third-party
launcher interface later, the project can evaluate it honestly.

## What automated tests do prove

The regression suite covers open and project-generated WonderSwan programs,
CPU and memory behavior, video provenance, compact image loading, save sizing,
console EEPROM, APF lifecycle, controls, settings transfer, display cadence,
audio transport, packaging, and many malformed-input cases. These results make
the development tree reviewable and catch regressions early.

They do not prove Quartus timing closure, electrical behavior, PocketOS user
experience, Dock controller behavior, HDMI presentation, commercial-title
compatibility, or original-panel authenticity. Those require the appropriate
build or physical evidence.

The full gate-by-gate record is in the [roadmap
status](https://github.com/RegionallyFamous/swansong-core/blob/main/PHASE_STATUS.md)
and [first-class Pocket compliance
matrix](https://github.com/RegionallyFamous/swansong-core/blob/main/POCKET_FIRST_CLASS.md).

## Commercial games and private evidence

The project has a hardware acceptance matrix for historically difficult title
scenarios, but every commercial case is still pending physical execution. A
passing simulator fixture is not proof that a named commercial game works.

Commercial ROMs, commercial ROM hashes, saves, and private
captures are not bundled. Testers use their own legally obtained dumps and
keep private evidence outside the repository. See the [known-title acceptance
guide](https://github.com/RegionallyFamous/swansong-core/blob/main/KNOWN_TITLE_COMPATIBILITY.md).

## Homebrew

Wonderful-generated `.ws` and `.wsc` programs have dedicated open regression
coverage. WonderWitch `.fx` programs need a FreyaBIOS/FreyaOS filesystem and
flash-cartridge environment that Swan Song does not currently provide. See the
[homebrew and WonderWitch
guide](https://github.com/RegionallyFamous/swansong-core/blob/main/HOMEBREW_WONDERWITCH.md).
