# Dialbug

Dialbug is a self-contained WonderSwan Color chiptune-player ROM with five
original songs and its own SD mobile-suit-style technician identity. Its
signature parts are amber armor, a split cyan visor, asymmetric tuning antenna,
round tuner core, circuit radiator backpack, and mixer gauntlet. SD proportions
keep the helmet, shoulders, chest, hands, and feet readable at 72×64 pixels.

The player provides four hardware channels, wavetable instruments, channel-3
hardware sweep, channel-4 noise percussion, per-frame envelopes, looping patterns, variable playback
speed, master volume, pause/restart, per-channel mute, and a live mix display.

## Interface art

The high-resolution Dialbug SD master, exact ImageGen prompt, and provenance
record are in `assets/source-art/`. Run
`python3 scripts/build_interface_art.py` to reproducibly reduce the mascot to a
72×64, four-color PNG. Wonderful Toolchain converts it into 9×8 native 2bpp
tiles. Titles, values, meters, and control hints are rendered exactly by ROM
code rather than generated as part of the image.

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

The output is `dialbug.wsc`.

## Technical provenance

DOI Hiroyuki's 2002 WonderWitch Humming Cat project was a research reference
for the compact VBlank-sequencer/player concept:

- <http://wwgp.qute.co.jp/2002/entry/00073/hcat/>
- <http://wwgp.qute.co.jp/2002/entry/00073/hcbeta04.lzh>

Dialbug does not use the Humming Cat name as its product identity and does not
copy its mascot, player binary, driver binary, or sample song data. The native
cartridge implementation, five-song score, title, mascot, and interface are new
for this project.

## Status

Version 0.1.0 is an emulator-qualified public release under
GPL-3.0-or-later. Its deterministic package includes the ROM, complete
corresponding Dialbug source, license, notices, and hash-bound evidence.

Do not claim physical WonderSwan-family, flash-cartridge, Analogue Pocket, or
Dock compatibility until the hardware checks in `release/` have been completed.
