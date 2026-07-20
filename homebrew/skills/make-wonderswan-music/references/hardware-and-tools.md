# WonderSwan sound hardware and tools

## Hardware facts

- The audio block has four channels. Every channel can use a 32-sample,
  4-bit wavetable.
- Channel 2 can switch to unsigned 8-bit PCM voice mode.
- Channel 3 can apply signed hardware frequency sweep.
- Channel 4 can switch from its wavetable to an LFSR noise generator with
  eight tap/sequence modes.
- Each wavetable occupies 16 bytes, so all four waves use a 64-byte,
  user-positioned block in internal RAM. Two 4-bit samples share each byte.
- Each normal channel has independent 4-bit left and right volume.
- The output path runs at 24 kHz. The internal speaker is an 8-bit mono mix;
  the headphone path is 16-bit stereo.
- The master clock is 3.072 MHz. A wave channel advances one sample every
  `2048 - divisor` clocks. For a 32-sample wave, the fundamental is
  `96000 / (2048 - divisor)` Hz.
- WonderSwan video refresh is about 75.47 Hz. A frame-driven engine must use
  that rate rather than assume 60 Hz.
- WonderSwan Color adds sound DMA and Hyper Voice. Hyper Voice is a separate
  stereo PCM path that is audible only through headphones; do not use it for
  music that must work through the built-in speaker.

## Register surface

- Frequency: ports `0x80` through `0x87`, two bytes per channel.
- Wavetable volume: `0x88` through `0x8B`, left nibble then right nibble.
- Sweep amount/time: `0x8C` and `0x8D`; sweep time is clocked at 375 Hz.
- Noise control: `0x8E`.
- Wavetable base: `0x8F`.
- Channel/mode control: `0x90`.
- Output control: `0x91`.

Prefer the installed libws names from `<ws/sound.h>` and `<ws/ports.h>` over
literal port numbers. Use `WS_SOUND_WAVE_HZ_TO_FREQ(hz, 32)` for pitch
conversion and `ws_sound_set_wavetable_address()` for the 64-byte wave block.

## Tool lanes

### Native ROM engine

Use C or assembly pattern data plus libws register access when the goal is a
self-contained cartridge image. Keep score data in ROM with `__far` where the
project's memory model requires it, and keep live voices/wavetables in internal
RAM.

### Furnace

Furnace supports the WonderSwan chip, its wavetable instrument editor, channel
4 noise, channel 3 sweep effects, audio rendering, VGM export, text export, and
developer-oriented command-stream export. It is excellent for auditioning and
sketching. Furnace does not itself provide a drop-in WonderSwan cartridge
player; integration still requires a compatible runtime driver or a deliberate
conversion step.

Useful WonderSwan effects in Furnace:

- `10xx`: change wavetable.
- `11xx`: set channel-4 noise mode.
- `12xx`: set channel-3 sweep period.
- `13xx`: set signed channel-3 sweep amount.

## Primary references

- Wonderful Toolchain target overview:
  <https://wonderful.asie.pl/doc/general/target-wonderswan/>
- WSdev Sound register documentation:
  <https://ws.nesdev.org/wiki/Sound>
- Wonderful Toolchain platform overview:
  <https://wonderful.asie.pl/wiki/doku.php?id=wswan:platform_overview>
- Furnace WonderSwan chip manual:
  <https://tildearrow.org/furnace/doc/v0.6/7-systems/wonderswan.html>
- Furnace export documentation:
  <https://tildearrow.org/furnace/doc/v0.6.5/2-interface/export.html>

When available locally, the installed Wonderful headers are the most precise
API reference:

- `/opt/wonderful/target/wswan/medium/include/ws/sound.h`
- `/opt/wonderful/target/wswan/medium/include/ws/ports.h`
