# Controls and Settings

> There is no verified release yet. These mappings and menu contracts are
> implemented and tested at source level, but the complete PocketOS 2.6.0
> Pocket and Dock experience still requires physical acceptance.

## Controls

**Control Layout** decides how Pocket's face and shoulder buttons map to the
WonderSwan button matrix. **Auto** follows the running game's native
orientation. **Horizontal** and **Vertical** keep the chosen button arrangement
even if a game changes orientation. This setting changes controls only: the
D-pad continues to follow the game's native directional matrix, and the screen
does not rotate.

| Pocket or Dock control | Horizontal layout | Vertical layout |
| --- | --- | --- |
| D-pad | Game-native directions | Game-native directions |
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
[`FIRST_CLASS_INPUT_DOCK.md`](https://github.com/RegionallyFamous/swansong-core/blob/main/FIRST_CLASS_INPUT_DOCK.md).

## Fast Forward

Hold Select for temporary 2.5× speed, or tap it to latch Fast Forward until the
next press. Dock controllers without a dedicated menu button may use a
PocketOS Select + Down menu chord. Swan Song uses PocketOS's focus notification
to block physical gameplay input and clear Fast Forward as the menu opens. It
requires a fresh valid neutral Pocket or Dock gamepad packet before controls
are rearmed, so a held menu chord cannot leak back into the game. This guard
is independent from Swan Song's menu-pause path: the held `00B0` focus level
pauses the emulated console, then menu exit resumes it even if controls are still
waiting for neutral rearm. Cartridge RTC wall time continues while paused. This
is a Swan Song product choice—Analogue permits a core to ignore `00B0` for
compatibility—not a requirement imposed on every openFPGA core. The internally
Exact notification/PAD ordering, audio, display, and resume behavior on current
firmware remain physical Pocket/Dock tests.

## System settings

- **System Type (reset):** `Auto`, `WonderSwan`, or `WonderSwan Color`. Auto
  follows cartridge metadata. Changing this option requires a reset.
- **Control Layout:** `Auto` follows the game's native orientation;
  `Horizontal` or `Vertical` keeps that face/shoulder-button arrangement.
  This does not rotate the picture or change the D-pad's native matrix.
- **CPU Turbo:** allows extra emulated CPU work per frame and can reduce some
  software slowdowns. It is an optional behavior change, not an accuracy
  requirement.
PocketChallenge v2 is intentionally not listed because its distinct machine
behavior and `.pc2` launch path are not implemented.

All nine persistent settings use Analogue's documented read/write Interact
behavior. PocketOS writes a choice before Reset Exit, and Swan Song reads the
requested value back at the same BRIDGE address so the menu can reflect the
core's state. For **System Type (reset)**, readback intentionally reports the
requested menu choice; the active Auto-resolved model does not replace that
choice. Quit/relaunch persistence and **Reset all to defaults** remain physical
Pocket acceptance tests.

## Video settings

- **Triple Buffer:** shows only complete frames, preventing producer/scanout
  tearing at the cost of buffered delivery and unavoidable skipped native
  frames. Off uses the lower-latency direct path and may tear.
- **Motion / LCD Response:** `Off` shows the newest sample. `2-Frame Blend`
  retains the familiar two-frame blend. `Persistence` uses a finite 50/25/25
  history model inspired by ares. `Complete Frames 60.9Hz` changes only the
  Pocket output cadence and, once priming completes, uses the newest completed
  frame. On a direct-to-buffered change, the live/direct picture remains visible
  for one producer-frame priming interval and retains the direct path's tearing
  risk; the steady-state complete-frame guarantee begins with the first
  completed buffered frame. It does not speed up the game, interpolate frames,
  emulate an LCD, or guarantee lower latency. All three non-Off choices request
  completed-frame buffering even when Triple Buffer is off. Standard remains
  the default; the 60.9 Hz option is experimental until Pocket and Dock
  verification is complete.
- **Display Orientation:** selects Pocket scaler presentation independently of
  the game's native input orientation.
- **Landscape 180°:** rotates landscape presentation by 180 degrees. It is not
  a mirror and does not remap controls.
- **Color Profile:** `Raw RGB444` is the neutral default. `Color LCD (ares)` is
  a reproducible optional cross-channel matrix based on a pinned ares
  implementation; it is not advertised as measured panel calibration.

The exact cadence and buffering math are documented in [Frame delivery
engineering](https://github.com/RegionallyFamous/swansong-core/blob/main/FRAME_DELIVERY.md).
The evidence and limitations behind the color and persistence options are in
the [screen-authenticity
contract](https://github.com/RegionallyFamous/swansong-core/blob/main/SCREEN_AUTHENTICITY.md).

## Sound setting

- **Audio in Fast Forward:** when enabled, sound continues while Fast Forward
  is active. The normal output target is signed stereo at 48 kHz.
