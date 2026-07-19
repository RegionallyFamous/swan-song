# Dialbug 0.1.0 development preview

Dialbug is a playable, self-contained WonderSwan Color music-player ROM with
five original chiptunes:

1. **Battery Glow** — 148 BPM
2. **Neon Raintrace** — 132 BPM
3. **Soft Reset Sunrise** — 106 BPM
4. **Last Save Point** — 164 BPM
5. **Signal Bloom** — 140 BPM

Dialbug has an independent name and original SD mobile-suit technician mascot:
an oversized mechanical helmet, amber armor, split cyan visor, asymmetric
tuning antenna, round tuner core, circuit radiator backpack, and mixer gauntlet.
It avoids named-suit replicas, classic twin V-fins, RX-78 color blocking, known
weapons, and faction marks. Earlier cat, insect, and tall-suit concepts and
their generated assets are not included.

DOI Hiroyuki's 2002 WonderWitch Humming Cat project remains credited only as a
technical research reference for the compact sequencer/player concept. Dialbug
does not include its binaries, tools, sample resources, name treatment, or
mascot artwork.

## What is verified

- Two clean Wonderful Toolchain builds produce identical 128 KiB ROMs.
- The ROM footer checksum is valid and independently accepted by Mednafen.
- The Swan Song ares engine boots all five tracks with isolated empty
  persistence; every track produces distinct, finite, non-silent audio.
- The combined plan exercises pause/continue, song changes, channel
  mute/unmute, and speed change.
- The ImageGen master is hash-locked and the runtime mascot is exactly 9×8
  hardware tiles.
- Mednafen records more than two complete loops of Battery Glow at 48 kHz
  stereo; the measured loop period is checked against its 148 BPM score.

## What is not verified

- No physical WonderSwan, WonderSwan Color, SwanCrystal, flash cartridge,
  Analogue Pocket, or Dock test has been performed.
- Public distribution remains pending a maintainer license declaration.
