# Screen-authenticity contract

This document separates reproducible digital behavior from claims that would
require measurements of original panels. No WonderSwan Color CSTN or
SwanCrystal TFT response curve was found in the reviewed primary/reference
sources, so Swan Song does not invent adjustable ghosting strengths or call an
emulator approximation hardware-calibrated.

## Evidence, in the project brief's required order

1. **Current FPGA core.** `gpu.vhd` emits the native 12-bit `rrrrggggbbbb`
   palette value. The pinned MiSTer wrapper expands a raw nibble by duplication
   (`{nibble,nibble}`) and offers equal-weight two/three-frame blend formulas;
   those inherited formulas are not exact endpoint-preserving averages and do
   not contain a panel-specific color or response model.
2. **ares `449b93716fb162632de2fd43bf2eba2064fa43f2`.** The pinned
   [WonderSwan color implementation](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/color.cpp#L1-L29)
   offers an optional cross-channel matrix for non-ASWAN models. Its comment
   says the SwanCrystal display is treated as similar to a Game Boy Color; it
   does not claim a measured WonderSwan Color panel profile. WonderSwan enables
   ares' generic
   [interframe blending](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/ppu.cpp#L30-L46),
   whose shared screen code recursively averages the current color with the
   previous filtered output
   [per channel](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/node/video/screen.cpp#L251-L266).
3. **Mednafen 1.32.1.** The official source archive, SHA-256
   `de7eb94ab66212ae7758376524368a8ab208234b33796625ca630547dbc83832`,
   maps every WonderSwan Color channel to `nibble * 17` in
   `src/wswan/gfx.cpp::WSwan_SetPixelFormat()`. Its WonderSwan module contains
   no temporal ghosting filter or alternate Color/SwanCrystal matrix. This is
   the neutral `Raw RGB444` contract.
4. **WSdev.** The pinned
   [palette documentation](https://ws.nesdev.org/w/index.php?title=Display/Palette&oldid=514)
   explicitly says there is no canonical palette across models. It identifies
   the mono FSTN display as approximately linear and GBP-like, WonderSwan Color
   as CSTN, and SwanCrystal as a GBC-like TFT with gamma near standard video.
   It supplies no response-time constants or colorimetric matrix.
5. **Analogue APF.** Official
   [`video.json` documentation](https://www.analogue.co/developer/docs/core-definition-files/video-json)
   recommends generic LCD modes for forward compatibility and requires pure
   full-range grayscale only when the display-mode notification requests it.
   It does not define a WonderSwan-specific display mode or publish temporal
   coefficients. Swan Song therefore retains generic `0x20`, `0x30`, and
   `0x40`; it does not relabel GBC/NGPC modes as WonderSwan hardware.

## Implemented digital models

`Raw RGB444` is the default and is exact:

```text
R8 = R4 × 17; G8 = G4 × 17; B8 = B4 × 17
```

`Color LCD (ares)` reproduces the high eight bits of the pinned ares matrix:

```text
R8 = floor((26R4 + 4G4 + 2B4) / 2)
G8 = floor((       24G4 + 8B4) / 2)
B8 = floor(( 6R4 + 4G4 + 22B4) / 2)
```

The maximum is 240, so `0xFFF` maps to `0xF0F0F0`; this is intentional and is
why the raw profile remains the neutral default. Color conversion happens to
each completed history sample before temporal processing and is enabled only
for color-system output, matching ares' non-ASWAN branch. Mono WonderSwan
grayscale stays on the raw, full-range path.

`Motion / LCD Response` has four values:

- `Off`: the newest sample only.
- `2-Frame Blend`: the existing rounded average of newest and previous
  completed frames.
- `Persistence`: `floor((2N + P + O) / 4)` per transformed eight-bit channel.
- `Complete Frames 60.9Hz`: the newest sample only, with the optional output
  cadence documented in `FRAME_DELIVERY.md`. It is not an LCD-response model.

The last formula is a **project-designed finite approximation**, not literal
ares output and not measured panel physics. Expanding ares' recursive 50%
average produces weights `1/2, 1/4, 1/8, ...`; Swan Song retains three complete
histories and collapses the unrepresented older tail onto `O`, yielding
`1/2, 1/4, 1/4`. This preserves constant colors and adds a causal-looking trail
without adding another framebuffer or an arbitrary strength menu.

Both temporal-response choices require completed-frame history. They therefore
enable buffering and intentionally include older image content. The 60.9 Hz
choice also forces completed-frame buffering but does not blend old pixels. Any
statement about end-to-end display or input latency must include that buffering policy.
The color matrix and arithmetic themselves are combinational, and every menu
change is applied only at a scanout frame boundary to avoid a partial-frame
profile seam.

## Verification and limits

`sim/rtl/apf_temporal_blend_tb.sv` checks:

- all 4,096 possible scalar newest/previous/oldest triples through all four
  temporal encodings, permuted across R/G/B;
- every one of the 4,096 RGB444 colors against the pinned ares matrix;
- every RGB444 color through every temporal encoding with adversarial,
  cross-channel history samples;
- raw and corrected primaries, black/white endpoints, 60.9 Hz newest-sample behavior,
  constant-color invariance, and the documented persistence step.

The settings CDC, source mutation contract, APF definition tests, and package
round-trip test bind the menu defaults, address `0x210`, arithmetic source, and
frame-boundary application. This proves deterministic RTL behavior only. It
does not prove that the optional profile or persistence model matches a
particular physical panel, lighting condition, production lot, or Pocket
display mode.

## Evidence needed for real panel calibration

A future calibrated profile needs controlled captures from at least one stock
WonderSwan Color and one stock SwanCrystal. The workload should show all 4,096
native colors plus black/white and primary transitions at native cadence. The
report must preserve console revision, panel condition, ambient illumination,
camera exposure/white balance, capture frame rate, raw files, spatial sampling
region, and uncertainty. Step-rise and step-fall curves must be fitted
separately if the panel is asymmetric. Only then should model-specific
coefficients be added, and they must remain optional until Pocket and Dock
captures verify the complete path.
