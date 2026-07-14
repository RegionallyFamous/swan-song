# First-class Pocket input and Dock contract

Research snapshot: 2026-07-13. This document separates what the current
Analogue openFPGA interface documents, what Swan Song implements, and what can
only be accepted on physical Pocket and Dock hardware.

## Primary sources

- Analogue [`input.json`](https://www.analogue.co/developer/docs/core-definition-files/input-json): the current developer page describes the Controls menu as read-only; per-asset files can replace its definition; at most four `default` controllers and eight named mappings per controller are allowed; names are limited to 19 characters; the only defined keys are A, B, X, Y, L, R, Start, and Select.
- Analogue [PAD bus](https://www.analogue.co/developer/docs/bus-communication): Pocket and Dock input switching is automatic; four controller slots are transported; type 1 is Pocket P1, types 2 and 3 are Dock gamepads, type 4 is keyboard, and type 5 is mouse. Digital buttons are in `key`; analog sticks and triggers are separate Dock-only values. The type field must be checked before interpreting a slot.
- Analogue [`core.json`](https://www.analogue.co/developer/docs/core-definition-files/core-json): `dock.supported` allows Dock; `dock.analog_output` describes upcoming analog *video timing*, not analog controller input.
- Analogue [`video.json`](https://www.analogue.co/developer/docs/core-definition-files/video-json): a core may define up to eight scaler slots with 0, 90, 180, or 270 degree presentation and optional Dock-specific aspect ratios.
- Analogue [`interact.json`](https://www.analogue.co/developer/docs/core-definition-files/interact-json): Pocket builds Core Settings from the Controls submenu, reloadable data slots, and custom interact entries. A per-asset Interact file completely replaces the core definition, and its persistent values are stored separately for that asset.
- Analogue [core-definition overview](https://www.analogue.co/developer/docs/core-definition-files): `info.txt` is limited to 32 lines, and the public docs still describe input remapping as a future feature.
- Analogue [openFPGA 1.1 beta 5 changelog](https://www.analogue.co/developer/docs/changelog/1-1-beta-5): the official developer changelog says existing cores became fully remappable per core through the OS, including reset-to-defaults and guided remap-all, without a core update. This is the missing historical primary source for the remapper claim, but it does not document current persistence, per-asset precedence, or Pocket-versus-Dock behavior.
- Analogue [Pocket firmware 2.4](https://www.analogue.co/support/pocket/firmware/2.4): the release notes nevertheless say beta controller remapping applies to all four controllers when Docked. This conflicts with the current developer pages and does not define persistence or per-asset scope.
- Analogue [Pocket firmware 2.6.0](https://www.analogue.co/support/pocket/firmware/2.6.0): current firmware on the research date adds more Dock controllers and a Recent category for openFPGA.
- Analogue [Pocket firmware 2.5](https://www.analogue.co/support/pocket/firmware/2.5): controllers without a menu button use the PocketOS Select + Down fallback chord; this is an OS action, not an openFPGA `input.json` key.

Two actively maintained public cores were checked as implementation
comparators at fixed commits. Both follow the same small, descriptive
`input.json` plus `dock.supported: true` pattern; neither exposes a private
remapping extension:

- agg23 NES at [`a09c51e` input](https://github.com/agg23/openfpga-NES/blob/a09c51e2487686a862d5ec660f515c4c2e0301b5/pkg/pocket/Cores/agg23.NES/input.json) and [`core.json`](https://github.com/agg23/openfpga-NES/blob/a09c51e2487686a862d5ec660f515c4c2e0301b5/pkg/pocket/Cores/agg23.NES/core.json)
- budude2 GBC at [`864253c` input](https://github.com/budude2/openfpga-GBC/blob/864253c6c2d902208db387caabb031574cdd8a5e/pkg/gbc/Cores/budude2.GBC/input.json) and [`core.json`](https://github.com/budude2/openfpga-GBC/blob/864253c6c2d902208db387caabb031574cdd8a5e/pkg/gbc/Cores/budude2.GBC/core.json)

## Implemented contract

| Capability | APF capability | Swan Song behavior |
|---|---|---|
| Pocket controls | Built-in controls arrive as type 1 in P1 | Accepted as digital P1 input |
| Dock controller | Digital and analog-capable pads arrive as types 2 and 3 | Both accepted; only their digital `key[15:0]` bits are used |
| Automatic handoff | APF switches internal and external controller data | No core-side Dock mode or controller-model table is needed |
| Four controller slots | PAD transports P1-P4 | Only P1 is consumed; WonderSwan gameplay is single-player |
| Analog sticks/triggers | Available separately for compatible Dock pads | Ignored; `dock.analog_output: false` does not change this |
| Keyboard and mouse | Types 4 and 5 have special packet layouts | Rejected by the type filter, preventing special data from becoming buttons |
| Disconnect/reserved type | Type 0 means absent; 7-F are reserved | Fail closed to all buttons released |
| Controls surface | Default and per-asset `input.json` definitions | Eight exact orientation-aware labels and default keys; PocketOS 2.6.0 editability/remapping behavior must be observed on Pocket and Dock |
| Control Layout | Persistent runtime Interact list | Auto follows the game's native orientation; Horizontal and Vertical force only the face/shoulder-button arrangement |
| Menu/system action | Owned by PocketOS and absent from the documented PAD key map | Select remains Fast Forward, while `00B0` blocks physical gameplay input until a fresh valid neutral Pocket/Dock packet arrives |
| Video orientation | Scaler slots can rotate presentation | 0 degree landscape, 270 degree portrait, and 180 degree landscape slots |
| Dock aspect | Optional per scaler slot | No Dock override; the same 14:9 source aspect is requested |

The source deliberately accepts type 3's digital button word while ignoring
its analog axes. Whether a particular controller or stick is translated into
D-pad bits is PocketOS/firmware behavior and is not claimed by this core.
Likewise, controller pairing, model compatibility, player ordering, and system
hotkeys belong to Dock/PocketOS. The core only receives APF's normalized slots.

## Display orientation and control layout

The emulated console's live native-orientation signal remains the source of
truth for the WonderSwan's game-visible orientation and directional matrix.
The user-facing **Display Orientation** setting selects only Pocket scaler
presentation. The separate **Control Layout** setting selects how A, B, X, Y,
L, and R feed the WonderSwan keypad:

- **Auto** follows the running game's native horizontal or vertical signal;
- **Horizontal** forces the horizontal face/shoulder-button arrangement; and
- **Vertical** forces the portrait-style face/shoulder-button arrangement.

Auto follows the game, including a game that changes its native orientation at
runtime. It does not detect or react to the player physically rotating Pocket.
Horizontal and Vertical are also controls-only overrides: they do not rotate
the image, select a scaler slot, change the emulated orientation signal, or
change the D-pad's game-native directional path.

| Pocket or normalized Dock control | Horizontal layout | Vertical layout |
|---|---|---|
| D-pad | Game-native directions (unchanged) | Game-native directions (unchanged) |
| A | A | X3 |
| B | B | X4 |
| X | Y3 | X2 |
| Y | Y4 | X1 |
| L | Y1 | A |
| R | Y2 | B |
| Start | Start | Start |
| Select | Fast Forward | Fast Forward |

In Auto, a portrait game therefore uses the Vertical column while Pocket can
remain physically upright: the game-native directional path serves its Y
directions, the four face buttons serve its X cluster, and L/R become A/B. The
same selected layout applies on Dock. On a television, the 270 degree scaler
slot rotates the image independently; APF's exact scaling and pillarboxing
remain a hardware/display acceptance item.

The descriptive names in `input.json` are therefore not cosmetic guesses.
They mirror the two-stage RTL mapping through `wonderswan.sv` and
`rtl/joypad.vhd`. A per-game Input preset supplies game-specific Controls text
and declared APF keycodes, but it does not choose the runtime Control Layout.
The conflicting public documentation is insufficient to promise what PocketOS
allows a user to edit, apply, reset, or persist.

### Per-title layout defaults

The preset helper can make Vertical (or Horizontal) the default for one ROM:

```sh
python3 scripts/pocket_per_game_preset.py \
  --sd-root /Volumes/POCKET \
  --asset "Vertical/Example.wsc" \
  --control-layout vertical
```

APF per-asset Interact files replace the complete core `interact.json`; they are
not merged as partial patches. The helper therefore clones the complete current
menu and changes its defaults. Regenerate an older per-title file if it predates
Control Layout. A persistent file already stored under
`/Settings/RegionallyFamous.SwanSong/Interact/...` can still override the new
default until the player chooses **Reset all to defaults** for that title. See
[Per-game Pocket presets](PER_GAME_PRESETS.md) for path mirroring, overwrite
safety, and the separate `--controls inherit` behavior.

## PocketOS actions and unavoidable limits

The documented PAD word has Start and Select, but no Analogue/menu/system bit,
and `input.json` has no keycode for one. System actions are handled outside the
core. On a Dock controller with no menu button, firmware 2.5 documents Select +
Down as the menu fallback. Swan Song uses Select for Fast Forward because all
other documented input keys are required by the WonderSwan matrix.

Swan Song now consumes the documented `00B0` focus notification in the native
PAD clock domain. While PocketOS owns focus, physical gameplay input is blocked
for Pocket and Dock alike. After focus returns, disconnect, keyboard, mouse,
reserved, stale, and held gamepad packets remain blocked; only a fresh valid
neutral type-1, type-2, or type-3 gamepad packet rearms input. The same guarded
level crosses into the system clock through a fail-closed synchronizer and
clears every Fast Forward latch, counter, and edge-history state. Host reset,
Reset Core/Console Setup reset, and a new title load clear that state too.

This focus boundary does not pause the emulated WonderSwan. The internally
injected **Console Setup** Start gesture is ORed in after physical PAD filtering
and remains available while the PocketOS menu is open. Physical hardware must
still prove the ordering of `00B0` and PAD updates on current firmware, including
the Select + Down fallback; source logic no longer depends on PocketOS fully
intercepting the chord.

There is no supported openFPGA metadata mechanism for:

- requiring Controls to be writable or storing core-defined user remaps;
- defining a separate Pocket-versus-Dock layout;
- assigning PocketOS menu, Home, Memories, or quick-load actions;
- selecting mappings from controller model names;
- turning an openFPGA core or ROM into a first-party Analogue Library entry.

Swan Song implements the alternate ergonomic layouts through its persistent
Control Layout Interact option and gameplay mapper. This does not extend APF's
`input.json` schema or create a core-owned PocketOS remap store.

## Physical acceptance gates

Run these on the release firmware (2.6.0 at the research date) before claiming
first-class Pocket/Dock input:

1. On Pocket, run one known horizontal and one known vertical game. In Auto, exercise every matrix direction, A/B, Start, held Fast Forward, and tapped/latching Fast Forward.
2. Confirm Auto follows live game orientation rather than physical Pocket rotation. Force Horizontal and Vertical and prove the face/shoulder mapping changes exactly as documented while the D-pad path, game-visible orientation, and presentation remain unchanged. Separately confirm Display Orientation and Landscape 180 affect presentation only.
3. On Dock, repeat the input matrix with one wired type-2 controller and one wireless analog-capable type-3 controller. Verify D-pad behavior explicitly; do not assume analog-stick-to-D-pad synthesis.
4. Hot-unplug and reconnect the Dock controller while holding a button. Confirm no stuck key and that P1 recovers without a core reset.
5. Use a controller with a dedicated menu button, then one requiring Select + Down. Confirm menu entry immediately suppresses gameplay, Fast Forward is cleared, held input does not reappear on exit, and a neutral release rearms controls without pausing the game.
6. Verify PocketOS reports Memories unavailable cleanly; Memories and Sleep/Wake remain disabled in this core.
7. Inspect 0, 270, and 180 degree output on Pocket and HDMI, including aspect, crop, display modes, mode transitions, and a vertical game's first frame.
8. Install a per-game Interact/Input preset with a non-Auto Control Layout. Confirm APF replacement lookup, the per-title default, and Reset all to defaults, then record the complete Controls behavior on firmware 2.6.0 for Pocket and Dock: displayed labels/defaults, whether editing is offered, and—if it is—application, relaunch persistence, and per-asset scope. Either an observed read-only screen or an observed beta remapper is evidence; neither may be assumed from the conflicting pages.
9. Confirm controllers in slots P2-P4, keyboard, mouse, absent, and reserved device types never control gameplay.

The source/metadata checks in
`scripts/pocket_input_dock_contract_test.py` lock the reviewable half of this
contract. They cannot replace these PocketOS, controller-firmware, HDMI, and
physical-device tests.
