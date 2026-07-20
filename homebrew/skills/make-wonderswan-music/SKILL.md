---
name: make-wonderswan-music
description: Compose, arrange, implement, and validate original WonderSwan or WonderSwan Color chiptunes using the four wavetable channels, channel-3 sweep, channel-4 noise, native C pattern engines, and optional Furnace sketches. Use for new or revised WonderSwan songs, instruments, wavetables, tempo and pattern data, ROM sound drivers, or emulator and audio proofs.
---

# Make WonderSwan Music

Build music around the console's real sound architecture, then prove the result
in the ROM. Prefer musical clarity and a reliable loop over densely filled
patterns.

## Route the task

1. Inspect the project's sound engine, event schema, instrument table, song
   data, build command, and existing audio proof before editing.
2. Use the existing native engine when the music must ship in a ROM. Do not
   replace a working engine with a tracker player without an explicit reason.
3. Use Furnace for sketching, wavetable auditioning, or reference renders when
   useful. Treat `.fur`, VGM, WAV, and command-stream exports as source or
   reference material, not automatically ROM-playable assets.
4. Read [hardware-and-tools.md](references/hardware-and-tools.md) before working
   on registers, wavetables, sweep, noise, PCM, or a new driver.
5. Read [composition-and-arrangement.md](references/composition-and-arrangement.md)
   before composing or materially rearranging a song.
6. Read [audience-and-production.md](references/audience-and-production.md)
   when the goal is broad listener appeal, repeat listening, an album, or a
   public music release.
7. When the project uses SWANFRAME's native pattern engine, also read
   [swanframe-engine.md](references/swanframe-engine.md).

## Compose

1. Write a brief containing mood, tempo, tonal center, hook, loop length, and
   the intended job of each channel. Name the listener lane: hardware-chip
   purist, game-soundtrack listener, or a specific electronic/pop genre.
2. Establish a one- or two-bar hook with melody and bass before adding harmony
   or percussion.
3. Give each channel one primary job. Let rests, gates, wave changes, stereo
   placement, and register separate the parts.
4. Use channel-specific features intentionally: channel 3 for sweep gestures;
   channel 4 for LFSR percussion. Do not request these effects on other
   channels unless the software engine emulates them.
5. Build an A/B/turnaround order rather than copying one pattern for the entire
   loop. Make the last pattern lead naturally back to the first.
6. For a standalone player track, default to 45-90 seconds of distinct musical
   form before the loop unless the brief explicitly calls for a short cue.
7. Keep every title, subtitle, pattern index, volume, gate, and note inside the
   engine's declared bounds.

## Implement and check

1. Preserve unrelated source and existing songs.
2. Add new instruments only when the arrangement needs a genuinely different
   envelope, wave, pan, sweep, or noise behavior.
3. Run `scripts/score_lint.py path/to/songs.c` for SWANFRAME-style C scores.
4. Run `scripts/score_audit.py path/to/songs.c` when evaluating a catalog for
   replay value, structural variety, or release readiness.
5. Build twice from clean state and compare ROM hashes when preparing a
   release.
6. Play the new song long enough to cross its loop boundary. Exercise song
   selection, pause/restart, speed, volume, and channel mute controls.
7. Capture emulator audio. Reject silence, clipping, DC-heavy output, timing
   drift, a broken loop, or a part that disappears on the mono speaker mix.
8. Review the isolated channels when the mix is muddy or the harmony is
   ambiguous.

## Quality bar

- Make the hook identifiable from melody and bass alone.
- Keep channel 4 rhythmic rather than continuously noisy.
- Keep bass fundamentals above the engine's reliable tuning floor.
- Avoid masking all four channels in the same octave and stereo position.
- Make the loop transition sound composed, not merely wrapped.
- Give a standalone track enough form and contrast to survive three immediate
  listens without the hook becoming irritating.
- Report what was tested in emulation and what remains untested on physical
  hardware.
