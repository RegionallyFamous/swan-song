# Controls and Settings

> There is no verified release yet. These mappings and menu contracts are
> implemented and tested at source level, but the complete PocketOS 2.6.0
> Pocket and Dock experience still requires physical acceptance.

## Controls

The running game's native orientation selects the WonderSwan button matrix.
Changing **Display Orientation** rotates presentation only; it does not remap
gameplay.

| Pocket or Dock control | Horizontal game | Vertical game |
| --- | --- | --- |
| D-pad | WonderSwan X directions | WonderSwan Y directions |
| A | A | X3 |
| B | B | X4 |
| X | Y3 | X2 |
| Y | Y4 | X1 |
| L | Y1 | A |
| R | Y2 | B |
| Start (`+`) | Start | Start |
| Select (`-`) | Fast Forward | Fast Forward |

Pocket's built-in controls and a Dock controller use this same Player 1 digital
mapping. Controllers in P2-P4, keyboards, and mice are not gameplay inputs for
this single-player core. Analog-capable Dock controllers are accepted, but
Swan Song consumes only the digital button word; PocketOS decides whether a
particular analog stick is translated into D-pad input.

The documentation boundary is preserved here in the wording used by the
project's technical contract.

Analogue's current developer pages describe the
`input.json` Controls UI as read-only.

official Pocket firmware 2.4 notes separately say beta Dock remapping
applies to all four controllers.

Firmware 2.6.0 Pocket and Dock hardware observation is
the acceptance gate.

Swan Song therefore declares useful labels and defaults
without promising whether PocketOS will offer editing, apply a remap, or
persist it. The researched contract and hardware matrix are in
[`FIRST_CLASS_INPUT_DOCK.md`](https://github.com/RegionallyFamous/swan-song/blob/main/FIRST_CLASS_INPUT_DOCK.md).

## Fast Forward

Hold Select for temporary 2.5× speed, or tap it to latch Fast Forward until the
next press. Dock controllers without a dedicated menu button may use a
PocketOS Select + Down menu chord. Whether the OS completely intercepts that
chord before Swan Song sees it remains a physical Dock test.

## System settings

- **System Type:** `Auto`, `WonderSwan`, or `WonderSwan Color`. Auto follows
  cartridge metadata. Changing this option requires a reset.
- **CPU Turbo:** allows extra emulated CPU work per frame and can reduce some
  software slowdowns. It is an optional behavior change, not an accuracy
  requirement.
- **Console Setup:** momentarily recreates the original Start-held power-on
  gesture so the user-supplied BIOS can open its owner screen.

PocketChallenge v2 is intentionally not listed because its distinct machine
behavior and `.pc2` launch path are not implemented.

## Video settings

- **Triple Buffer:** shows only complete frames, preventing producer/scanout
  tearing at the cost of buffered delivery and unavoidable skipped native
  frames. Off uses the lower-latency direct path and may tear.
- **LCD Response:** `Off` shows the newest sample. `2-Frame Blend` retains the
  familiar two-frame blend. `Persistence` uses a finite 50/25/25 history model
  inspired by ares. The latter two choices imply buffering. Neither is claimed
  as a measurement of an original WonderSwan panel.
- **Display Orientation:** selects Pocket scaler presentation independently of
  the game's native input orientation.
- **Landscape 180°:** rotates landscape presentation by 180 degrees. It is not
  a mirror and does not remap controls.
- **Color Profile:** `Raw RGB444` is the neutral default. `Color LCD (ares)` is
  a reproducible optional cross-channel matrix based on a pinned ares
  implementation; it is not advertised as measured panel calibration.

The exact cadence and buffering math are documented in [Frame delivery
engineering](https://github.com/RegionallyFamous/swan-song/blob/main/FRAME_DELIVERY.md).
The evidence and limitations behind the color and persistence options are in
the [screen-authenticity
contract](https://github.com/RegionallyFamous/swan-song/blob/main/SCREEN_AUTHENTICITY.md).

## Sound setting

- **Audio in Fast Forward:** when enabled, sound continues while Fast Forward
  is active. The normal output target is signed stereo at 48 kHz.
