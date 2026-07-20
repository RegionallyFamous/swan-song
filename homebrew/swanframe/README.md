# SWANFRAME

SWANFRAME is a self-contained WonderSwan Color chiptune-player ROM with five
original songs and its own SD mobile-suit-style technician identity. Its
signature parts are an asymmetric tuning antenna, split optical visor, round
tuner core, circuit radiator backpack, and mixer gauntlet. The current Night
Drive colorway uses hot-orchid armor, phosphor-mint sensors, smoky indigo, and
midnight violet. SD proportions keep the character readable at 72×64 pixels.

The player provides four hardware channels, wavetable instruments, channel-3
hardware sweep, channel-4 noise percussion, per-frame envelopes, looping patterns, variable playback
speed, master volume, pause/restart, per-channel mute, and a live mix display.

## Interface art

The high-resolution SWANFRAME SD master, both ImageGen cockpit studies, exact
prompts, and provenance records are in `assets/source-art/`. The approved v2
study establishes the Night Drive palette and visual hierarchy; it is not
pasted into the ROM. Run `python3 scripts/build_interface_art.py` to
reproducibly produce a 72×64 four-color mascot and eight native UI glyphs.
Wonderful Toolchain converts those into 2bpp tiles. The large track display,
waveform lanes, progress rail, values, and button dock remain live ROM code.

## Controls

- X-pad left/right: previous/next song
- X-pad up/down: volume up/down
- A: pause or continue
- B: restart the current song
- Start: cycle 50%, 75%, 100%, 125%, and 150% speed
- Y1/Y2/Y3/Y4: mute channels 1/2/3/4

## Build

```sh
source /opt/wonderful/bin/wf-env
python3 scripts/build_interface_art.py
make
```

The output is `swanframe.wsc`.

## Technical provenance

DOI Hiroyuki's 2002 WonderWitch Humming Cat project was a research reference
for the compact VBlank-sequencer/player concept:

- <http://wwgp.qute.co.jp/2002/entry/00073/hcat/>
- <http://wwgp.qute.co.jp/2002/entry/00073/hcbeta04.lzh>

SWANFRAME does not use the Humming Cat name as its product identity and does not
copy its mascot, player binary, driver binary, or sample song data. The native
cartridge implementation, five-song score, title, mascot, and interface are new
for this project.

## Status

Version 0.1.0 is an emulator-qualified public release under
GPL-3.0-or-later. Its deterministic package includes the ROM, complete
corresponding SWANFRAME source, license, notices, and hash-bound evidence.

Do not claim physical WonderSwan-family, flash-cartridge, Analogue Pocket, or
Dock compatibility until the hardware checks in `release/` have been completed.
