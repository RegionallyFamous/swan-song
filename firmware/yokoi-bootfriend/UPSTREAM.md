# Upstream and license

Regionally Famous modified this fork for Yokoi Boot and first published this
version on 2026-07-19. It is not an unmodified upstream BootFriend build.

Yokoi Boot is a modified fork of Adrian Siekierka's BootFriend, pinned from
[`asiekierka/ws-bootfriend`](https://github.com/asiekierka/ws-bootfriend) at
commit `d474ac06aec813e44e51b851adc45a3f5f09db14` (2026-06-14).

The RAM loader and its splash-execution technique remain licensed under
GPL-3.0-or-later; see `COPYING`. `hardware.inc` retains its original zlib-style
notice. Yokoi changes are marked in `yokoi_boot.asm` and include the `yK`
signature, version byte, rectangular tilemap, palette, and generated logo
tiles. Yokoi is not the original BootFriend project and should not be reported
as an upstream BootFriend build.
