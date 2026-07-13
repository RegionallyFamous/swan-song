# First-class Pocket input and Dock contract

Research snapshot: 2026-07-13. This document separates what the current
Analogue openFPGA interface documents, what Swan Song implements, and what can
only be accepted on physical Pocket and Dock hardware.

## Primary sources

- Analogue [`input.json`](https://www.analogue.co/developer/docs/core-definition-files/input-json): the Controls menu is currently read-only; per-asset files can replace its labels; at most four `default` controllers and eight named mappings per controller are allowed; names are limited to 19 characters; the only defined keys are A, B, X, Y, L, R, Start, and Select.
- Analogue [PAD bus](https://www.analogue.co/developer/docs/bus-communication): Pocket and Dock input switching is automatic; four controller slots are transported; type 1 is Pocket P1, types 2 and 3 are Dock gamepads, type 4 is keyboard, and type 5 is mouse. Digital buttons are in `key`; analog sticks and triggers are separate Dock-only values. The type field must be checked before interpreting a slot.
- Analogue [`core.json`](https://www.analogue.co/developer/docs/core-definition-files/core-json): `dock.supported` allows Dock; `dock.analog_output` describes upcoming analog *video timing*, not analog controller input.
- Analogue [`video.json`](https://www.analogue.co/developer/docs/core-definition-files/video-json): a core may define up to eight scaler slots with 0, 90, 180, or 270 degree presentation and optional Dock-specific aspect ratios.
- Analogue [`interact.json`](https://www.analogue.co/developer/docs/core-definition-files/interact-json): Pocket builds Core Settings from the read-only Controls submenu, reloadable data slots, and custom interact entries. Persistent interact values may also be overridden per asset.
- Analogue [core-definition overview](https://www.analogue.co/developer/docs/core-definition-files): `info.txt` is limited to 32 lines, and the public docs still describe input remapping as a future feature.
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
| Controls help | Default and per-asset `input.json` labels | Eight exact orientation-aware labels; read-only, not a remapper |
| Menu/system action | Owned by PocketOS and absent from the documented PAD key map | Not assigned by RTL; Select remains the gameplay Fast Forward input |
| Video orientation | Scaler slots can rotate presentation | 0 degree landscape, 270 degree portrait, and 180 degree landscape slots |
| Dock aspect | Optional per scaler slot | No Dock override; the same 14:9 source aspect is requested |

The source deliberately accepts type 3's digital button word while ignoring
its analog axes. Whether a particular controller or stick is translated into
D-pad bits is PocketOS/firmware behavior and is not claimed by this core.
Likewise, controller pairing, model compatibility, player ordering, and system
hotkeys belong to Dock/PocketOS. The core only receives APF's normalized slots.

## Orientation and held-normally ergonomics

The emulated console's live native-orientation signal selects the WonderSwan
button matrix. The user-facing Display Orientation setting selects only the
Pocket scaler presentation. This distinction is intentional: forcing a frame
rotation must not silently change what the emulated game reads.

| Pocket or normalized Dock control | Horizontal game | Vertical game |
|---|---|---|
| D-pad | X1-X4 directions | Y1-Y4 directions |
| A | A | X3 |
| B | B | X4 |
| X | Y3 | X2 |
| Y | Y4 | X1 |
| L | Y1 | A |
| R | Y2 | B |
| Start | Start | Start |
| Select | Fast Forward | Fast Forward |

This makes portrait games playable while Pocket remains physically upright:
the D-pad becomes the WonderSwan Y cluster, the four face buttons become its X
cluster, and L/R become A/B. The same normalized layout applies on Dock. On a
television, the 270 degree slot rotates the image; APF's exact scaling and
pillarboxing remain a hardware/display acceptance item.

The descriptive names in `input.json` are therefore not cosmetic guesses.
They mirror the two-stage RTL mapping through `wonderswan.sv` and
`rtl/joypad.vhd`. A per-game Input preset may provide game-specific help text,
but under the current documented interface it cannot choose a different
physical layout.

## PocketOS actions and unavoidable limits

The documented PAD word has Start and Select, but no Analogue/menu/system bit,
and `input.json` has no keycode for one. System actions are handled outside the
core. On a Dock controller with no menu button, firmware 2.5 documents Select +
Down as the menu fallback. Swan Song uses Select for Fast Forward because all
other documented input keys are required by the WonderSwan matrix. Whether the
OS fully intercepts that chord before the Fast Forward tap/latch logic observes
it must be tested on current firmware; metadata cannot solve that collision.

There is no supported openFPGA metadata mechanism for:

- making Controls writable or storing core-defined user remaps;
- defining a separate Pocket-versus-Dock layout;
- assigning PocketOS menu, Home, Memories, or quick-load actions;
- selecting mappings from controller model names;
- turning an openFPGA core or ROM into a first-party Analogue Library entry.

An alternate ergonomic layout would require a new persistent Interact option
and gameplay RTL mux, followed by hardware testing. It is not introduced by
this audit because the current mapping is internally consistent and no narrow
input bug was proven.

## Physical acceptance gates

Run these on the release firmware (2.6.0 at the research date) before claiming
first-class Pocket/Dock input:

1. On Pocket, run one known horizontal and one known vertical game. Exercise every matrix direction, A/B, Start, held Fast Forward, and tapped/latching Fast Forward.
2. Confirm Auto follows live game orientation. Force Horizontal and Vertical and prove presentation changes without changing the game-visible matrix. Confirm Landscape 180 affects presentation only.
3. On Dock, repeat the input matrix with one wired type-2 controller and one wireless analog-capable type-3 controller. Verify D-pad behavior explicitly; do not assume analog-stick-to-D-pad synthesis.
4. Hot-unplug and reconnect the Dock controller while holding a button. Confirm no stuck key and that P1 recovers without a core reset.
5. Use a controller with a dedicated menu button, then one requiring Select + Down. Confirm menu entry/exit does not leave Fast Forward active or inject a harmful game input.
6. Verify PocketOS reports Memories unavailable cleanly; Memories and Sleep/Wake remain disabled in this core.
7. Inspect 0, 270, and 180 degree output on Pocket and HDMI, including aspect, crop, display modes, mode transitions, and a vertical game's first frame.
8. Install a per-game Input preset. Confirm its labels replace the default Controls help on 2.6.0 and that the screen remains read-only.
9. Confirm controllers in slots P2-P4, keyboard, mouse, absent, and reserved device types never control gameplay.

The source/metadata checks in
`scripts/pocket_input_dock_contract_test.py` lock the reviewable half of this
contract. They cannot replace these PocketOS, controller-firmware, HDMI, and
physical-device tests.
