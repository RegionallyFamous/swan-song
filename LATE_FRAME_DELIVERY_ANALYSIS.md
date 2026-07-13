# Phase 4 late complete-frame experiment

Status: **isolated prototype; not instantiated and not present in the Quartus
project.** It is a safer and materially lower-age candidate than beam racing,
but it still needs a new ownership handshake, a scaler-slot migration, Quartus
timing closure, and measurements on Pocket and Dock before production use.

## APF-safe exact-60 geometry

Analogue's official [Bus Communication](https://www.analogue.co/developer/docs/bus-communication)
documentation permits 16x16 through 800x720 active video, approximately 47-61
Hz refresh, 1-50 MHz pixel clocks, and any amount of inactive pixels or entire
inactive lines. It requires one-cycle VS and HS, HS no earlier than three clocks
after VS, one inactive clock between HS and DE, and one inactive clock between
DE falling and the next HS.

The candidate keeps the existing 6.144 MHz clock and uses a 256x400 raster:

`6,144,000 / (256 * 400) = 60.000000000 Hz`

The APF-bus phase model is:

| Event | Position |
|---|---:|
| VS | x=0, y=0 |
| HS | x=7 on every line |
| Late completed-frame selection | x=0, y=256 |
| Active pixels | x=9..232, y=256..399 (224x144) |
| Scaler EOL command | x=233 on active lines |

The seven-clock HS position matches the delay already imposed by
`apf_video_bus`. Clock x=8 is inactive between HS and DE. After the EOL word,
22 clocks remain before line wrap and the next line's HS does not occur until
x=7, comfortably exceeding the other APF gap. The 256 entirely inactive lines
are explicitly allowed by the published protocol.

At x=0/y=256, the gate chooses only a completed frame. The active image begins
nine pixel clocks later. A completion after this gate remains pending for a
later output frame and cannot change the selected bank during active scanout.
If no completion exists, the previous complete, slot-matched presentation is
repeated for the entire frame. A live or shortened WonderSwan LCD Final Line
therefore cannot expose stale rows: it can only delay the next completion.

## Exact APF-input content age

The default native producer period is 488,448 system clocks (13.25 ms). The
model enumerates every producer-clock completion phase for both paths rather
than assuming a favorable reset alignment:

- Current 397x258 selection has a 36-clock phase quantum: 36 reset residues by
  13,568 selections each, covering all 488,448 producer phases.
- Candidate 256x400 selection has a 3,072-clock phase quantum: 3,072 reset
  residues by 159 selections each, again covering all 488,448 phases.

The calculations include the average position of all 32,256 active pixels and
use x=9 for the candidate's guarded first DE position:

| APF-input content-age metric | Current 397x258 | Late 256x400 |
|---|---:|---:|
| Mean completion-to-active-pixel age | 15.532389..15.533339 ms | 9.582113..9.665419 ms |
| Mean completion-to-first-pixel age | 10.894206..10.895155 ms | 6.584798..6.668104 ms |

Candidate worst phase versus current best phase is still 5.866970 ms newer at
the average active pixel and 4.226101 ms newer at the first pixel. The late gate
is 393,216 system clocks, exactly 128 native lines or 10.666667 ms, after VS.
Across every native phase residue, 393,216/488,448 = 128/159 = 80.503145% of
output frames have an opportunity to select one native generation newer than a
VS-time selection.

These are APF input-bus content-age bounds, not input-to-photon claims. They do
not include controller polling, game response, Pocket scaler buffering, LCD
response, or Dock behavior. Dynamic orientation deferrals also deliberately
trade one repeated output frame for correctness and are excluded from the
steady-orientation timing opportunity.

## Scaler-slot next-frame semantics

The official APF document says a Set Scaler Slot EOL command takes effect on
the **next frame**. The implementation must therefore track two distinct
states:

- `expected_applied_slot`: the slot expected to own the APF frame currently
  being transmitted;
- `command_for_next_frame`: the last slot command transmitted during the
  current frame, expected to become applied only after the next boundary.

A complete candidate may be promoted at the late gate only when its stored slot
equals `expected_applied_slot`. If it differs, the safe sequence is:

1. Claim and protect that completed candidate bank.
2. Repeat the current complete frame only if its slot matches the currently
   applied slot; otherwise fail closed to blank.
3. Emit the candidate's slot in this frame's EOL words.
4. At the following frame boundary, advance that command to the expected slot.
5. At the following late gate, promote the protected candidate under the now
   matching applied slot.

The isolated module backpressures later candidates while a slot-mismatched bank
is scheduled. This is intentional: allowing pending supersession to recycle the
scheduled bank would recreate the ownership failure found in the beam-race
experiment. A production arbiter must implement `candidate_take` and
`scheduled_protect_*` semantics or an equivalently proven reservation policy.

The command also has to change before the first active-line EOL at x=233. The
current `apf_scaler_selector` exposes a new command only at `frame_start_video`,
so it cannot be reused unchanged for a decision made at y=256. A migration must
separate the expected-applied slot from the live EOL-command slot and provide a
CDC-safe update in the long interval before the first EOL.

### Production dynamic-orientation repair

This next-frame rule is not unique to the candidate. The former production
path promoted per-bank orientation at `scanout_frame_boundary` before the APF
slot commanded in the following raster could take effect. That real ordering
issue is now repaired independently of this late-frame candidate by
`apf_orientation_transition_guard`, protected-pending framebank ownership, and
the explicit scaler command transport.

The former problematic ordering was:

| Frame | Presented slot | Expected applied slot | EOL command for next | Result |
|---|---:|---:|---:|---|
| 0 | 0 | 0 | 0 | matched |
| 1 | 1 | 0 | 1 | potential mismatch |
| 2 | 1 | 1 | 1 | matched |

Production now repeats slot 0 in frame 1 while commanding slot 1, then presents
the reserved slot-1 frame in frame 2. The production guard and its cross-domain
APF-next-frame proof are documented in `ORIENTATION_TRANSITION.md`. Physical
Pocket behavior must still be captured, but the digital contract no longer
depends on an ambiguous live-orientation ordering.

## Executable prototype evidence

- `src/fpga/core/apf_late_frame_candidate.sv` contains the exact-60 cadence,
  APF bus phases, late complete-frame gate, no-completion repeat, explicit
  applied-versus-next slot state, mismatched-candidate reservation, bank
  protection request, and blank fail-closed path. It is absent from
  `wonderswan.sv` and `ap_core.qsf`.
- `sim/rtl/apf_late_frame_candidate_tb.sv` exhaustively counts one default
  256x400 raster (400 HS, 32,256 DE pixels, 144 EOL words, one VS, one late
  gate) and adversarially checks no-completion repeat, two opposite-direction
  slot deferrals, scheduled-bank protection/backpressure, next-frame slot
  advancement, and cold-start blank fallback.
- `scripts/late_frame_delivery.py` derives exact phase-age bounds, geometry,
  the 128/159 newer-generation opportunity, and current-versus-safe dynamic
  orientation timelines. Its unit test locks all reset residues and ensures the
  prototype remains outside production RTL.

## Production gates

Do not integrate the candidate until all of the following are complete:

1. Adapt the production protected-pending handshake to the late gate without
   allowing a late candidate to recycle visible/protected history.
2. Reuse the production explicit expected-applied/command state while proving
   the later decision still reaches the first active-line EOL safely.
3. Keep presentation settings and temporal-history rotation frame-atomic at the
   late gate without changing game-visible WonderSwan orientation/input state.
4. Confirm APF VS/HS/DE/EOL waveforms in SignalTap, close Quartus 21.1.1 timing,
   and capture stable output on both Pocket and Dock.
5. Measure actual input-to-photon latency and orientation transitions before
   making user-facing latency or first-class presentation claims.
