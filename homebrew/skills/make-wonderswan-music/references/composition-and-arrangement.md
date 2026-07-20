# Composition and arrangement

## Start with a compact brief

Define:

- a concrete scene or feeling;
- BPM and meter;
- tonal center or mode;
- a singable two- to eight-note hook;
- loop length in patterns/bars;
- channel roles;
- one WonderSwan-specific sonic feature.

## Default channel plan

This is a starting point, not a law:

| Channel | Primary job | Useful character |
| --- | --- | --- |
| 1 | lead or countermelody | square, pulse, saw, bell |
| 2 | bass or second melodic voice | triangle, pulse; reserve PCM only when required |
| 3 | harmony, arpeggio, pad, or sweep accent | triangle, pulse, sine, hardware sweep |
| 4 | kick/snare/hat or occasional wave voice | LFSR noise plus short gated wave kick |

Channel 4's mode is global to that voice at a moment in time. A wave kick and a
noise snare can share it if the engine changes the mode on each trigger.

## Writing for four voices

- Establish bass roots and melody before filling harmony.
- Implied harmony is often stronger than block chords. Use bass plus a
  third/seventh, or a short arpeggio, to state the chord.
- Avoid continuous events on every even row. Syncopation and rests make the
  waveforms feel more articulate.
- Keep a stable register gap: bass commonly C2-C3, harmony C3-C5, melody C4-C6.
- Use gates to create articulation. A note that retriggers every row with a
  long release can blur into clicks and mud.
- Use A/B contrast through contour, rhythm, register, or instrumentation; do
  not rely only on transposition.
- Write the turnaround last. Its final bass and melody tones should create
  forward pull into the opening downbeat.

## Sound design

- Square: focused lead and classic chip tone.
- Narrow pulse: hollow, bright, and useful for arpeggios.
- Triangle: strong bass and soft pad foundation.
- Saw: aggressive lead; use shorter gates or lower volume to avoid masking.
- Sine-like table: bell, soft lead, or sweep accent.
- Hardware sweep: use on channel 3 as a short transition, rise, chirp, or
  tension gesture. Keep the amount/tick interval conservative to avoid divisor
  wraparound.
- Noise: use long LFSR sequences for snare-like noise and short sequences for
  metallic hats. Reset the LFSR on a fresh hit when deterministic attacks are
  desired.
- Stereo: create width with modest complementary pan values. Always verify the
  mono speaker sum; stereo separation must not be required to hear a part.

## Loop forms that fit a small ROM

- 4 bars: `A A B T`
- 8 bars: `A A B A / B B A T`
- 12 bars: `A A B A / C C B T / A B C T`

Reuse pattern data through an order list, but give the turnaround its own
pattern so the seam is deliberate.

## Review passes

1. Melody and bass only: verify hook, harmony, and loop.
2. Add channel 3: check that it clarifies rather than competes.
3. Add percussion: confirm accents support the phrase.
4. Listen through mono and stereo paths.
5. Inspect each channel in isolation for clicks, stuck envelopes, unintended
   pitches, and excessive release tails.
6. Capture more than one complete loop and check both the musical seam and the
   measured period.
