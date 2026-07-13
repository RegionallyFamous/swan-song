# Swan Song Pocket core icon

Swan Song includes an original, generic pixel-swan mark at
`dist/Cores/agg23.WonderSwan/icon.bin`. It does not reproduce Bandai's
WonderSwan wordmark, console trade dress, or third-party artwork. The existing
platform image remains separately credited in `README.md`.

The live [Analogue packaging documentation](https://www.analogue.co/developer/docs/packaging-a-core),
accessed 2026-07-13, defines the core-author icon contract:

- a 36x36-pixel canvas;
- 16-bit monochrome pixels with brightness in the upper byte;
- only `0x0000` black and `0xFF00` white for a black/white icon;
- a bitmap stored rotated 90 degrees counter-clockwise; and
- `icon.bin` in the core folder.

The same page recommends a 2x2 pixel scale and warns that Pocket may invert the
icon palette. The Swan Song design therefore uses an 18x18 source grid expanded
to 36x36, a one-logical-pixel safe margin, a white canvas, and a bold black
silhouette. The byte order and polarity also match Analogue's official
`open-fpga/core-template` v1.3.0 `dist/icon.bin` example at commit
`da3a021b1eaf742604d86d8dc9b33a6666263e6a`.

## Reproduce and inspect

The checked-in binary is generated without Pillow or another image dependency:

```sh
python3 scripts/generate_core_icon.py
python3 scripts/generate_core_icon.py --check
python3 scripts/generate_core_icon.py --check --preview /tmp/swan-song-icon.pgm
python3 scripts/generate_core_icon_test.py
```

`scripts/package_validator.py` independently checks the 2,592-byte dimensions
and the two allowed 16-bit pixel values. `scripts/package_core_test.py` proves
that `icon.bin` reaches the APF ZIP and rejects malformed dimensions or pixel
values. The generated-icon test additionally decodes the stored rotation back
to the upright source, locks the reviewed digest, and rejects a stale binary.

Host-side validation proves the documented layout, deterministic generation,
and packaging path. Legibility and centering in both the positive and negative
Core List and Core Boot Screen contexts remain a physical Pocket acceptance
gate; no hardware observation is inferred here.
