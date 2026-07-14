# Phase 4 beam-race experiment

Status: **nominal geometry is promising, but production integration is rejected
until two missing safety contracts exist.** The current direct and
newest-complete-frame modes remain unchanged.

## Candidate

At each APF output boundary, latch the current producer writer bank only if its
address-zero write has already been observed. The first APF active pixel does
not appear until line 66, pixel 31, providing 157,398 system clocks (4.269694
ms) from the boundary. Normal WonderSwan production writes one pixel every 12
system clocks and one line every 3,072 clocks; APF reads a pixel every 6 clocks
and one line every 2,382 clocks. The producer therefore starts ahead but the
faster scanout consumes that lead through the frame.

The exact model checks all 32,256 pixels. At the worst phase—producer pixel zero
coincident with the output boundary—the last pixel (143,223) is written 57,386
system clocks (1.556695 ms) before its conservative read deadline, after a
four-clock RAM/pipeline guard. Any later eligible producer phase only increases
that margin. The model enumerates all 441,973 system-clock phases from first
pixel through the visible sweep, so stable default timing has no read-before-
write counterexample.

This could select a currently rendering native frame instead of waiting for its
completion and the following output boundary. Under the default 159-line
producer, exact phase-superperiod analysis makes 12,277 of 13,568 output frames
(90.484965%) eligible. Each eligible output would show pixels from one native
generation later than newest-complete buffering, a 13.25 ms content-capture age
reduction; fallback frames are unchanged. Averaged across all output boundaries,
that is 11.989258 ms of content-age reduction. This is not an input-to-photon
claim: controller sampling, game response, APF scaling, and the panel are
outside the model.

Direct mode can expose equally new or newer writes but permits cross-generation
tearing. The candidate does not beat direct mode's minimum latency; its value
would be complete-frame coherence with near-direct freshness. It only beats the
existing buffered mode on eligible frames, subject to the missing safety
contracts below.

## Why it is not safe to integrate

### 1. LCD Final Line is live and programmable

[WSdev documents LCD Final Line `$16`](https://ws.nesdev.org/wiki/Display/IO_Ports#LCD_Final_Line)
as the final line before the display counter restarts, with default 158, and
notes that a display shorter than 144 lines never reaches normal VBlank. The
translated GPU compares live `LCD_VTOTAL` on every line; it does not latch a
guaranteed frame length at address zero.

A concrete legal-register counterexample is Final Line 143. LCD delivery is
one line delayed, so the producer wraps after publishing row 142. APF later
reads row 143/address 32,032 from stale bank contents. A write from 158 to 143 after the
output boundary creates the same failure even if the frame began normally.
Once earlier rows have been displayed, falling back to a complete bank for row
143 would itself create a cross-generation tear.

Therefore a guard based only on observed progress cannot prove that future
pixels will exist. Requiring the last pixel before selection collapses the
candidate back to the existing complete-frame mode. Making Final Line frame-
latched would change emulated hardware behavior without a source proving that
the real device latches it.

### 2. The current five-bank arbiter does not reserve a beam bank

The current arbiter protects completed history, not an in-progress writer
latched by scanout. If the selected writer completes and a second producer frame
completes before the next output boundary, the pending-supersession branch
recycles the first bank as the new writer. Normal default timing may keep those
new writes behind already-read addresses, but that is not an ownership
guarantee and fails under accelerated production or changed frame timing.

A production design needs a `protect_valid/protect_bank` contract through the
entire output frame. Five banks can plausibly support a beam frame, two older
temporal histories, one writer, and one pending frame, but that requires a new
arbiter policy and exhaustive transition proof. The isolated candidate exports
the protection request; the current arbiter intentionally does not consume it.

Fast-forward must also force complete-frame fallback. The candidate has an
explicit `normal_speed` prerequisite and fails closed when it is false.

## Prototype evidence

- `src/fpga/core/apf_beam_race_candidate.sv` implements the conservative
  writer-start latch, frame-atomic bank selection, normal-speed gate, explicit
  future-producer-contract gate, and bank-protection request. It is not in the
  Quartus project and is not instantiated.
- `sim/rtl/apf_beam_race_candidate_tb.sv` proves fail-closed behavior without
  writer start, without the missing producer contract, and during accelerated
  production; it also proves bank latching/protection and conservative handling
  of coincident first-pixel/output-boundary events.
- `scripts/beam_race_safety.py` proves the nominal geometry across every pixel
  and eligible phase, then locks the programmable-frame and arbiter-reuse
  counterexamples.

The experiment should be revisited only if a source-backed producer contract
can guarantee all 144 rows after selection without changing WonderSwan-visible
register semantics, and a protected-bank arbiter is separately proven. Until
then, advertising this as tear-free low latency would be incorrect.
