# Pocket orientation-transition contract

## Result

Production buffered scanout now keeps a completed WonderSwan frame and its
Pocket scaler slot atomic across game-driven and menu-driven orientation
changes. The previous ordering could promote portrait pixels before the APF
slot command for portrait had taken effect. The repair deliberately repeats
one immutable frame while the new command matures. Direct scanout, which has
no immutable frame to repeat, sends a valid black raster during the unsafe
interval.

This change does not integrate the isolated late-frame cadence and does not
change the WonderSwan's live orientation bit or X/Y keypad behavior.

## Published APF rule

Analogue documents two facts that govern the design:

- [`video.json`](https://www.analogue.co/developer/docs/core-definition-files/video-json)
  may define up to eight scaler modes and cores may switch among them at
  runtime.
- A Set Scaler Slot command placed after a line takes effect on the **next
  frame**; if a frame contains several commands, only the last one takes
  effect ([APF bus communication](https://www.analogue.co/developer/docs/bus-communication)).

Swan Song defines slot 0 as landscape, slot 1 as 270-degree portrait, and slot
2 as landscape rotated 180 degrees. A command is not evidence that the slot is
already applied.

## Production timeline

The core's system-domain frame boundary is at the end of x=396/y=257. APF VS
is generated at x=320/y=1 of the following raster. There are conservatively
717 complete 6.144 MHz video-clock opportunities (about 116.7 microseconds)
between those events. This is far longer than the acknowledged bundled-data
CDC needs, and the constrained two-bit legal-slot payload is already captured in
`pending_slot_video` before VS.

For a landscape-to-portrait transition:

| Point | Presented pixels | Modeled APF applied slot | EOL slot emitted in frame | Action |
|---|---|---:|---:|---|
| F0 active | landscape history | 0 | 0 | matched |
| B0, end F0 | landscape history | 0 | — | reserve portrait bank; request slot 1 |
| F1 active | repeated landscape history | 0 | 1 | keep reserved bank immutable |
| B1, end F1 | portrait bank selected in vertical blank | 0 until F2 VS | — | promote reserved bank |
| F2 active | portrait bank | 1 | 1 | matched |

Although presentation bookkeeping changes at B1, no active pixel is sent
between B1 and F2 VS. APF consumes F1's last slot-1 EOL command at F2 VS,
before F2's active area begins. An additional defer stage would repeat a second
frame unnecessarily.

## Ownership and fail-closed behavior

[`apf_orientation_transition_guard.sv`](src/fpga/core/apf_orientation_transition_guard.sv)
tracks the slot being emitted, the slot expected to become applied, and the
slot associated with the presented bank.

When a complete buffered candidate needs another slot:

1. `defer_candidate` prevents its immediate promotion.
2. The framebank arbiter protects that exact pending bank.
3. Later producer completions reuse the unselected writer and are deliberately
   dropped; they cannot supersede, recycle, or tear the protected bank.
4. Existing immutable history repeats while the new slot is emitted.
5. The protected bank is promoted at the following system boundary, inside
   vertical blank, for the APF frame where the new slot becomes applied.

A cold buffered transition with no safe history is black until the protected
bank and slot agree. Direct mode and direct-to-buffer priming also black
immediately whenever live pixels require a slot different from the modeled
applied slot. The raster, sync, and EOL command stream remain valid.

Menu-only transforms do not need a new pixel bank. The same immutable history
is repeated under the old slot for one frame, then reused under the newly
applied slot. Portrait always takes precedence over landscape 180 degrees.

## Executable evidence

- `apf_orientation_transition_guard_tb.sv` covers both transition directions,
  menu-only forcing, cold portrait startup, direct and direct-to-buffer black,
  coincident producer/consumer completion, and three producer completions
  dropped while a pending bank remains protected.
- `apf_orientation_delivery_e2e_tb.sv` connects the production guard to the
  production scaler-selector CDC, preserves the real 6:1 clock relationship
  and 397x258 frame length, sweeps all six relative clock residues (the worst
  completes the video-domain capture in three clocks against the conservative
  717-clock budget), models APF's documented next-frame rule, checks exact EOL
  encoding and guard/applied estimates, and proves no active buffered or direct
  frame is exposed under the wrong slot.
- `apf_scaler_selector_tb.sv` uses unrelated clock phases, exercises rapid
  supersession and asynchronous reset, verifies the deliberately conservative
  coincident-request behavior, and proves the new command is safely pending
  within the 717-clock production boundary-to-VS budget.
- Existing framebank and per-bank orientation benches continue to prove bank
  ownership, queued supersession, and metadata association.

These are digital proofs, not physical Pocket measurements. Release still
requires Quartus timing/resource closure and Pocket/Dock testing for native
orientation changes, all menu orientation modes, landscape 180 degrees,
direct/buffered modes, reset, fast-forward, grayscale/display modes, and
producer completions near both transition boundaries.

## Public implementation survey

Research was pinned to source revisions instead of moving branches:

- Analogue's public core template at
  [`da3a021b1eaf742604d86d8dc9b33a6666263e6a`](https://github.com/open-fpga/core-template/commit/da3a021b1eaf742604d86d8dc9b33a6666263e6a)
  demonstrates the APF bus shape but only a static scaler slot; it does not
  prove a dynamic bank/slot handoff.
- The upstream openFPGA WonderSwan release at
  [`073213a2e5992cff23b174d17763cb6354ee862b`](https://github.com/agg23/openfpga-wonderswan/commit/073213a2e5992cff23b174d17763cb6354ee862b)
  drives the live orientation choice into EOL commands. It does not reserve a
  completed frame while APF's next-frame slot state catches up.
- Jotego's public `jtcores` tree was inspected at
  [`57d80ad7a9c151bd5cf2779449d3376037c4d97d`](https://github.com/jotego/jtcores/commit/57d80ad7a9c151bd5cf2779449d3376037c4d97d).
  Its Pocket target is a private submodule pinned there to
  `b4a87b2aa75c76c22d8a36fda64f1897b4c17b78`, so the relevant integration is
  not publicly auditable.

No publicly inspectable mature core found in this survey proved a game-driven
dynamic orientation change atomic with completed-frame ownership. The
production contract here is therefore derived directly from Analogue's
published next-frame rule and locked by local end-to-end simulation rather
than inferred from another core.
