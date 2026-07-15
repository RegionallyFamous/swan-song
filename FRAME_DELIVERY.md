# Frame delivery engineering

Swan Song converts a 75.471698 Hz WonderSwan producer into an APF-safe output.
Standard mode is 59.984769 Hz. An optional, non-default complete-frame mode is
60.905252 Hz. Both keep the native machine and audio at their original cadence;
they change only how frames are delivered to Pocket's scaler.

## Source constraints

- [WSdev timing](https://ws.nesdev.org/wiki/Timing) specifies a 3.072 MHz
  display clock, 256 clocks per line, and 159 lines per frame. Therefore the
  native producer is exactly `3,072,000 / (256 * 159) = 75.471698113 Hz` under
  the project's 12.288 MHz clock assumption.
- Analogue's official [Bus Communication](https://www.analogue.co/developer/docs/bus-communication)
  specification accepts 47 Hz to approximately 61 Hz, 1-50 MHz pixel clocks,
  one-cycle VS/HS pulses, at least one clock between sync and DE, and stable
  synchronous RGB/control.
- Analogue's official [openFPGA core template at pinned commit `da3a021`](https://github.com/open-fpga/core-template/blob/da3a021b1eaf742604d86d8dc9b33a6666263e6a/src/fpga/core/core_top.v#L499-L569)
  demonstrates integer raster totals chosen to produce exact 60 Hz. It does
  not prescribe a 401-pixel line or an asynchronous WonderSwan conversion
  policy.
- The upstream [MiSTer WonderSwan core](https://github.com/MiSTer-devel/WonderSwan_MiSTer/blob/30f74aa4c02856763721a2ed00c8feed55300893/README.md#refresh-rate)
  documents the same user-facing choice: direct 60 Hz with tearing or
  complete-frame buffering with additional lag. It does not supply an
  APF-specific cadence improvement.

## Corrected output cadence

The inherited output used `401 * 258` pixel clocks at 6.144 MHz, producing only
59.386417677 Hz while being described as 60 Hz. The corrected raster uses
`397 * 258` clocks:

| Metric | Inherited | Corrected |
|---|---:|---:|
| APF refresh | 59.386417677 Hz | 59.984769492 Hz |
| Error from 60 Hz | -1.022637% | -0.025384% |
| Output frame period | 16.838867 ms | 16.670898 ms |
| Native producer frames necessarily skipped per second in complete-frame mode | 16.085280 | 15.486929 |
| Skipped-frame reduction | — | 0.598352/s (3.72%) |

The 224-pixel active region, 258 line count, sync width, and all APF blanking
margins remain unchanged. Shortening only the late horizontal blanking tail
leaves 44 pixel clocks after HS deassertion before the next line and therefore
comfortably exceeds APF's one-clock minimum.

An alternative `400 * 256` raster would equal exactly 60 Hz at 6.144 MHz, but
it would remove two complete lines and change the established 258-HS vertical
frame geometry. That is a broader scaler/sync change than this correction
needs. With 258 lines held invariant, the ideal 60 Hz horizontal total is
`6,144,000 / (60 * 258) = 396.899...`; 397 is the nearest integer. A 391-pixel
line would approach APF's approximate 61 Hz ceiling and skip fewer producer
frames, but provides less documented tolerance and is not a nominal-60-Hz
choice. The 397x258 raster therefore minimizes nominal-60-Hz cadence error while
preserving the already-tested vertical, VS, and active-area placement.

## Optional complete-frame 60.9 Hz mode

`Motion / LCD Response > Complete Frames 60.9Hz` shortens the late horizontal
blanking tail by another six pixels, producing a 391x258 raster. It always
requests newest-complete-frame buffering even when the separate Triple Buffer
switch is off. A direct-to-buffered change keeps the live/direct picture visible
for one producer-frame priming interval; immutable completed-frame presentation
begins with the first completed buffered frame. It does not speed up the
WonderSwan, interpolate frames, emulate an LCD, or change audio pitch.

| Metric | Standard complete frames | Optional 60.9 Hz complete frames |
|---|---:|---:|
| APF refresh | 59.984769492 Hz | 60.905251888 Hz |
| Output frame period | 16.670898 ms | 16.418945 ms |
| Native producer frames necessarily skipped per second | 15.486929 | 14.566446 |
| Skip-event spacing | every 3 or 4 output frames | every 4 or 5 output frames |
| Drop-rate reduction | — | 0.920482/s (5.94%) |

The 391-pixel line still leaves 38 pixel clocks after HS deassertion, well over
APF's one-clock minimum. Its 60.905252 Hz rate is only 0.094748 Hz below APF's
documented approximate 61 Hz ceiling, however. Analogue does not publish the
Pocket panel's or Dock HDMI path's conversion behavior at this cadence. The
option is therefore experimental and non-default until PocketOS Developer
Statistics reports the measured rate as `ok` and the complete Pocket/Dock
hardware matrix passes. It must not be described as a latency improvement or
as subjectively smoother before those captures exist.

## Complete-frame cadence and latency boundary

The five-bank arbiter already selects the newest complete producer frame at
each output boundary. No additional queue can lower its completion-to-selection
age. Reset and save-state restoration do not establish a fixed producer/output
event phase, so the metric model does not assume coincident boundaries. The
two periods have a 36-system-clock phase quantum. Across every possible phase
residue, both the inherited and corrected rasters have the same complete-frame
age envelope: 0 to 13.249973 ms. A fixed phase's mean lies between 6.624512 and
6.625461 ms. The cadence correction is therefore not represented as a buffer-
latency reduction.

It does improve motion delivery. In a 13,568-output-frame phase superperiod,
the corrected raster receives 17,071 native frames and necessarily skips 3,503.
Skipped producer frames remain isolated: 3,059 skip events are four output
transitions apart and 444 are three apart. The inherited cadence skipped 3,675
frames, with 2,543 four-transition gaps and 1,132 three-transition gaps.

Direct mode uses the standard output period and remains intentionally
tear-permitting. The optional 60.9 Hz mode beats direct mode only on complete-
frame coherence and beats standard buffering only on the modeled drop cadence.
No claim is made about Pocket scaler latency, LCD response, Dock timing,
input-to-photon latency, or subjective smoothness without physical measurement.

## Executable evidence

- `sim/rtl/apf_scanout_cadence_tb.sv` exhaustively advances two complete
  397x258 rasters and two 391x258 rasters at the production divide-by-six
  enable, checks every held and advanced coordinate, proves 614,556 and 605,268
  system clocks per frame, and checks the frame-boundary mode transition.
- `sim/rtl/apf_video_bus_tb.sv` checks two complete frames of APF bus timing at
  the corrected cadence.
- `scripts/frame_delivery_metrics.py` derives both production modes' phase-
  superperiod, drop spacing, and phase-parameterized frame-age envelope using
  integer/Fraction arithmetic; its unit test locks every possible 36-cycle
  reset/event residue and explicitly prevents a false buffered-latency claim.

The current source still needs fresh Quartus 21.1.1 timing closure. Standard
and optional-mode measurements on physical Pocket and Dock remain required
hardware gates.
