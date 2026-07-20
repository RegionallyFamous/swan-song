# Audience appeal and release production

Use this reference when the goal is not merely valid chip audio, but music that
people may choose to replay. There is no universal recipe for taste. Treat the
rules below as research-backed production hypotheses, then test them with the
actual audience.

## Separate three kinds of success

1. **Hardware authenticity:** the ROM uses the real WonderSwan sound system and
   survives its speaker, timing, memory, and channel constraints.
2. **Musical identity:** a listener can recognize the hook, mood, and track from
   the score rather than from chip timbre alone.
3. **Audience fit:** the track gives a named group something familiar enough to
   enter and distinctive enough to remember.

Do not use "chiptune" as the whole brief. Chiptune listeners span hardware-
authentic chip music, bitpop, soundtrack music, and hybrids with styles such as
reggae and modern electronic music. Choose a musical lane first, then make the
WonderSwan the instrument that gives that lane a new voice.

## Findings translated into writing rules

### Familiar frame, distinctive signal

Repeated exposure and familiarity with a musical style are strong predictors
of liking, while excessive exact repetition can produce fatigue. Give the
listener a known frame--for example synthwave, drum and bass, city pop, ambient,
or heroic game music--and reserve one or two details for the track's identity.

- State a two- to eight-note hook within the first two to four bars.
- Repeat the hook exactly once so it can be learned.
- Return to it in a changed register, rhythm, harmony, instrument, or ending.
- Make one bass rhythm and one WonderSwan gesture part of the track's identity.
- Avoid introducing a new idea on every bar; continuity is part of catchiness.

### Predictability with controlled surprise

Music-perception research supports a productive middle ground: listeners need
enough regularity to form expectations, plus enough deviation to reward
attention. Groove research likewise finds the strongest urge to move around
moderate rhythmic complexity rather than maximal simplicity or syncopation.

- Keep a clearly audible pulse.
- Put syncopation in one or two parts, not every part simultaneously.
- Let bass or percussion establish the grid while melody pushes against it.
- Use a fill, rest, pickup, chord substitution, or sweep to mark a phrase end.
- Change one meaningful layer every four to eight bars.
- Make rare effects rare. A sweep on every chord becomes accompaniment; a
  sweep at the transition becomes a signature.

Individual preference still matters. Research has found listener groups with
opposing preferences for simpler and more complex music. Do not average every
listener into an imaginary universal audience; test the intended lane.

### Build a form, not a microloop

Short loops reveal their seam quickly and leave little room for contrast. A
2019 album of original WonderSwan music used pieces from 1:09 to 2:03. That is a
useful native-platform comparison, not a mandatory duration.

For a standalone ROM player, use these project heuristics:

- 45-90 seconds of distinct form before looping;
- 24-48 bars for most energetic tracks, depending on BPM;
- a meaningful change every four to eight bars;
- a full-intensity hook no more than three times before the loop;
- a composed turnaround whose last event creates forward pull;
- for an album render, a second changed pass and a real ending may extend the
  piece beyond the in-ROM loop.

One practical 40-bar form is:

`INTRO 4 / A 8 / A' 8 / B 8 / BREAK 4 / A'' 4 / TURN 4`

Variation does not require new pattern data everywhere. Keep the motif while
changing one dimension at a time: accompaniment density, register, bass
rhythm, drum fill, harmony tone, wavetable, gate, or stereo position.

### Use the four voices as a band

- Channel 1: phrase the hook like a lead player. Leave at least one clear rest
  in a two-bar phrase so the melody can breathe.
- Channel 2: give the bass a memorable rhythm, not only root notes on beats 1
  and 3. Preserve a stable low-register foundation.
- Channel 3: supply a countermelody, chord implication, or occasional sweep.
  Do not spend the whole song shadowing the bass root.
- Channel 4: make the kick/snare pulse legible, then add a limited number of
  offbeat hats, anticipations, and phrase-ending fills.

Audit melody and bass alone. If the hook, groove, and harmony disappear, more
wavetable polish will not rescue the composition.

## Listener test for a small homebrew release

Run a compact test before calling a track finished.

### Recruit by listener lane

Aim for 12-18 people across three groups when practical:

- hardware chiptune listeners;
- game-soundtrack listeners;
- listeners from the track's borrowed genre, such as synthwave or drum and
  bass.

Keep the group labels in the results. A polarized track may be a strong success
for its chosen lane even when its overall average is ordinary.

### Test without selling the answer

1. Randomize unlabeled 25-35 second excerpts. Do not show title, art, or which
   version is newer.
2. Ask for 1-9 ratings of liking, expressiveness, distinctiveness, and desire to
   hear the full track. Record familiarity with the style separately.
3. Play the complete loop three times. Ask when the repetition became obvious
   and whether it became pleasant, neutral, or irritating.
4. After a short distraction, ask the listener to hum, tap, or describe the
   hook. Recognition is more useful than asking whether it was "catchy."
5. Compare revisions as a randomized A/B test. Include one duplicated excerpt
   to expose inconsistent responses.
6. Repeat the strongest candidates on another day. Immediate repetition and
   growing familiarity are not the same listening condition.

A practical project gate--not a scientific law--is: the intended listener lane
prefers the revision in a blind A/B test, at least half can reproduce or
identify the hook, and no more than one quarter call the third loop irritating.

## Release treatment

Keep two deliverables when publishing outside the ROM:

- **ROM-authentic version:** direct hardware/emulator behavior, mono-safe, no
  effects the console cannot produce.
- **Album master:** the same performance with restrained EQ, level matching,
  and compression if needed for modern playback. Do not smear the waveform
  character with default reverb or widening.

Shovel Knight's developers used an analogous boundary: hardware-valid source
and note-programmed effects, followed by restrained EQ/compression for modern
playback while avoiding reverb and stereo processing that would erase the raw
character.

## Evidence and benchmarks

- Madison and Schioelde, repeated listening and familiarity:
  <https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2017.00147/full>
- Kraus, predictability, complexity, and musical reward:
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC7117902/>
- Stupacher, Wrede, and Vuust, rhythmic complexity and groove:
  <https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0266902>
- Gucluturk et al., opposing listener complexity preferences:
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC6457315/>
- Worrall, repetition, listener fatigue, and expressive variation in games:
  <https://etheses.whiterose.ac.uk/id/eprint/38684/>
- Reid, the breadth of chiptune identities and hybrid genres:
  <https://link.springer.com/article/10.1007/s40869-018-0070-y>
- Martins, practical contrast and loop-management patterns:
  <https://www.gamedeveloper.com/audio/rethinking-the-audio-loop-in-games>
- Disasterpeace on evolving musical ideas, direct game testing, and dynamic
  variation: <https://disasterpeace.com/blog/tag.MIDI.collaboration>
- Yacht Club Games on authentic tracker source and restrained mastering:
  <https://www.yachtclubgames.com/blog/breaking-the-nes/>
- hydden's original native WonderSwan EP and track durations:
  <https://hydden.bandcamp.com/album/wonderswan-sound-etude-ep-vol-1>
