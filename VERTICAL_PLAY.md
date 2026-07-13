# Vertical play contract

WonderSwan vertical presentation is a three-part contract: the emulated game
chooses its native keypad/GPU orientation, the core carries that orientation
beside the completed frame that owns the pixels, and Pocket rotates only the
selected output frame. Menu and per-game presentation overrides remain outside
the emulated machine and never rewrite its keypad state.

## APF geometry

Analogue's official [`video.json`](https://www.analogue.co/developer/docs/core-definition-files/video-json)
definition makes `width` and `height` the active input raster and expresses
rotation separately. The core therefore correctly keeps all three scaler slots
at the native 224x144 raster and square-pixel 14:9 aspect:

| Slot | Rotation | Displayed shape | Purpose |
|---:|---:|---:|---|
| 0 | 0 degrees | 14:9 | Native horizontal |
| 1 | 270 degrees | 9:14 after rotation | Native vertical |
| 2 | 180 degrees | 14:9 | Optional landscape inversion |

Swapping width/height or aspect fields in slot 1 would describe a different
input raster and risks double-rotated scaling. The official specification
allows runtime slot switching by the core; the EOL command selects one of these
declared slots without changing the 224x144 active video bus. Generic LCD modes
may separately integer-scale width and height and therefore may not preserve an
arbitrary aspect perfectly, which Analogue documents as a host scaler limit.
The core cannot and should not compensate by cropping or altering its raster.

The inherited agg23 Pocket core used the same 224x144, 14:9, 270-degree vertical
slot. The inspected Analogue template and agg23 NES, PC Engine, and SNES trees
use the same active-raster/aspect field semantics but contain no rotated mode,
so they neither contradict nor add a second rotation convention.

## Frame-bound orientation

The 75.471698 Hz producer can outrun the approximately 60 Hz APF consumer.
Five frame banks let a newer completed frame supersede an older pending frame,
while scanout can retain up to three immutable history frames for LCD response.
The live WonderSwan `vertical` bit can consequently be newer than the pixels
currently visible. Driving the scaler from that live bit could rotate an older
queued frame early during a title's runtime orientation change.

`apf_frame_orientation.sv` stores one orientation bit for each physical bank at
producer completion. Buffered presentation reads the bit belonging to
`history_newest`; pending supersession naturally follows bank ownership. Direct
mode still permits pixel tearing by design, but latches orientation only at an
output frame boundary. Reset erases all bank metadata before a new title can
reuse retained framebuffer RAM.

This presentation metadata is intentionally one-way. The live `vertical` bit
continues to drive the emulated GPU and keypad matrix immediately. `Display
Orientation` and `Landscape 180 degrees` can override Pocket presentation, but
they do not alter game-visible input behavior.

## Input behavior

The original hardware exposes X and Y four-button clusters. The current native
RTL rotates their matrix interpretation using the console's own LCD orientation
bit. Pocket's default mapping therefore keeps the D-pad directional in both
modes while moving the remaining X/Y cluster and A/B functions across the six
face/trigger inputs. This matches the documented hardware matrix: the current
[WSdev keypad reference](https://ws.nesdev.org/wiki/Keypad) enumerates distinct
X1-X4 and Y1-Y4 rows, and
[Mednafen's WonderSwan documentation](https://mednafen.github.io/documentation/wswan.html)
exposes both clusters as independent game-visible inputs. The core's
orientation-dependent matrix preserves that independence; it does not wire the
same Pocket key to both native clusters at once. Analogue permits at most eight mappings in
[`input.json`](https://www.analogue.co/developer/docs/core-definition-files/input-json),
so Start and Fast Forward consume the last two default entries. The official
per-asset override path can provide title-specific Controls definitions and
labels. Swan Song's generator clones the default bindings and does not claim an
editable runtime remapper.

## Verification boundary

The focused frame-orientation simulation covers startup portrait capture,
direct-mode mid-frame changes, queued-frame supersession, poisoned live state,
coincident producer/consumer boundaries, empty consumer boundaries, buffer
disable, and reset. The existing scaler simulation proves only legal slots are
published and applies changes at APF frame start. Source contracts prove the
module is integrated and included in Quartus and regression inputs.

Physical Pocket and Dock tests remain required to certify screenshot
orientation, full-frame containment, generic LCD integer scaling, menu changes,
and dynamic horizontal/vertical transitions. Source geometry and simulation do
not prove undocumented host-scaler behavior.
