# SWANFRAME native music engine

Read this when working in a repository containing SWANFRAME's `src/music.c`,
`src/music.h`, and `src/songs.c`.

## Score model

- `SWANFRAME_PATTERN_ROWS` is 16. At the normal speed setting, each row is a
  sixteenth note, so one pattern is one 4/4 bar.
- An event is `EV(note, instrument, volume, gate_rows)`.
- `N` means no new event and lets the current voice continue.
- `OFF` starts the active voice's release stage.
- Notes are available from C2 through C7 with macros such as `C(4)`, `FS(5)`,
  and `AS(3)`.
- Event volume is 0-15; use 1-15 for audible events.
- Gate length is measured in pattern rows. Keep it between 1 and 16.
- A song has a title (23 characters maximum), subtitle (26 maximum), BPM,
  order length, and an order list of pattern indices.
- Normal loop duration is `order_length * 16 * 15 / BPM` seconds.
- `SWANFRAME_MAX_ORDER` bounds the form. Increase it deliberately when moving
  from eight-bar proof tracks to release-length arrangements, then rebuild and
  test navigation and progress displays that derive from total step count.

## Existing instrument roles

- Melodic: `LEAD`, `PULSE`, `BELL`, `SAW`, `PLUCK`.
- Foundation: `BASS`, `PAD`.
- Software harmony: `MINARP`, `MAJARP`.
- Percussion: `KICK`, `SNARE`, `HAT`; place noise instruments on channel 4.
- Hardware gesture: `SWEEP`; place it on channel 3.

The runtime rewrites wavetables per note, applies ADSR-like envelopes in
software once per video frame, and uses per-instrument left/right volume.
Channel 4 changes between wave and noise mode on triggers. Channel 3 sweep must
not have its frequency register overwritten every frame while the hardware
effect is active.

## Add a song

1. Write a brief and a one-pattern hook.
2. Add two or three named pattern blocks to `swanframe_patterns`.
3. Add a `swanframe_songs` entry with a bounded order list.
4. Run the skill's `scripts/score_lint.py` against `src/songs.c`.
5. Make the UI derive the total song count from `swanframe_song_count`; remove
   hard-coded `/ 04` labels.
6. Add a playtest plan that selects the new song and runs beyond its complete
   loop.
7. Update verification metadata and capture the new song's frame/audio proof.

For a catalog or release-readiness review, also run
`scripts/score_audit.py path/to/src/songs.c`. It reports loop duration,
normalized form, pattern diversity, channel trigger density, and catalog-wide
form reuse without treating stylistic heuristics as compile errors.

## Build and proof sequence

Run clean and build as separate invocations because a combined `make clean all`
can retain dependency knowledge that the clean target then removes:

```sh
source /opt/wonderful/bin/wf-env
make clean
make
```

Then boot the ROM in the project's emulator workflow, select the new track,
capture more than one loop, and run the release verifier. For a release, repeat
the clean build and compare SHA-256 hashes.
