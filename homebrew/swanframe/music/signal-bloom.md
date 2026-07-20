# Signal Bloom

- Scene: a quiet service robot sends a handshake into low orbit and receives a
  bright, slightly mysterious reply.
- Tempo and meter: 140 BPM, 4/4, sixteenth-note engine rows.
- Tonal center: E minor, with a B-major-colored dominant turnaround.
- Hook: E-G-B, answered by A-G-F-sharp and a high E pickup.
- Form: eight bars, `A A B A / B B A T`.
- Loop duration: approximately 13.714 seconds at 100% speed.

## Channel plan

1. Pluck/lead melody, moving between the E-minor hook and a wider B section.
2. Triangle bass outlining E minor, C, G, D, A minor, and B.
3. Sine-like hardware sweep replies; signed amount `+2` every 24 ticks of the
   375 Hz sweep clock, producing a restrained upward gesture.
4. Wave-table kick plus long-sequence snare and short metallic hat noise.

## Initial proof

- SWANFRAME score lint: pass (15 patterns, 137 populated rows, 5 songs).
- Wonderful Toolchain build: pass.
- SwanSong full loop: 1,400 frames, non-silent stereo audio, peak 0.38575026.
- SwanSong isolated final-window peaks: channel 1 0.12566361; channel 2
  0.07353656; channel 3 0.07539817; channel 4 0.11555749.
- Physical WonderSwan and headphone-adapter listening: pending.
