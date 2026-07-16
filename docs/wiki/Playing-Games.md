# Playing Games

> Swan Song is still in development and has no verified public release. This
> guide describes the intended player experience; Startup Action, Recent,
> title switching, saves, and menus still require final Pocket hardware
> acceptance.

## Start a game

1. Open **openFPGA** on the Pocket.
2. Choose **Swan Song**.
3. Select a `.ws` or `.wsc` file from `/Assets/wonderswan/common/`.

Swan Song uses its built-in open IPL and does not ask for an external BIOS.

Swan Song asks Pocket to remember the last selected cartridge. Use **Core
Settings > Cartridge** to change games. Selecting a new title performs a full
restart so the outgoing save can be flushed before the next game begins.

For a shorter power-on route, choose **Startup Action > openFPGA**. PocketOS
2.6.0 also has a host-owned openFPGA **Recent** category. Public APF
documentation does not let a core pin or pre-seed that list, and final relaunch
behavior is still a physical-hardware test item. The exact Settings menu path
is deliberately not prescribed because Analogue reorganized those menus in
2.6.0 and does not document the complete path.

Swan Song cannot add itself or individual ROMs to Analogue's first-party
Library. That is a PocketOS boundary, not missing core artwork. The detailed
research is in the [Pocket launcher and Library
audit](https://github.com/RegionallyFamous/swansong-core/blob/main/POCKET_LAUNCHER_LIBRARY.md).

Swan Song keeps the mono and Color owner data in separate persistent console
EEPROM files. Their final quit, relaunch, model-switch, title-switch, and
power-cycle behavior remains part of hardware acceptance.

## Horizontal and vertical games

WonderSwan software can change its native orientation. Swan Song uses that
native signal for the game-visible button matrix when **Control Layout** is set
to **Auto**. Choose **Horizontal** or **Vertical** to keep that face- and
shoulder-button arrangement when a game changes orientation. The D-pad still
follows the game's native directional matrix.

**Display Orientation** controls only how Pocket presents the completed
picture. It does not change **Control Layout**, the D-pad matrix, or what the
game reads.

See [Controls and
Settings](https://github.com/RegionallyFamous/swansong-core/wiki/Controls-and-Settings)
for the two layouts and display options.

## Fast Forward

- Hold Pocket **Select (`-`)** for temporary 2.5× Fast Forward.
- Tap it to latch Fast Forward on.
- Press it again to return to normal speed.

The **Audio in Fast Forward** setting decides whether sound continues while
Fast Forward is active.

## Per-game presets

Advanced users can create local per-game defaults for display orientation,
Control Layout, color, buffering, LCD response, CPU Turbo, Fast Forward audio,
and descriptive controls. Presets stay on your own SD card and do not inspect
or catalogue ROM contents. PocketOS behavior around editable controls is still
being verified.
See the [per-game preset
guide](https://github.com/RegionallyFamous/swansong-core/blob/main/PER_GAME_PRESETS.md).

## Resetting remembered choices

Pocket's **Reset all to defaults** action clears the remembered cartridge
choice along with core settings. If a title appears to have been forgotten
after that action, select it again normally.
