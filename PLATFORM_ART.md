# Swan Wake platform art

Swan Song ships an original openFPGA platform image named **Swan Wake** at
`dist/Platforms/_images/wonderswan.bin`. Regionally Famous designed the image
for Swan Song and implemented its deterministic generator. The white swan is
the exact 18x18 logical mark already maintained in
`scripts/generate_core_icon.py`; the wake, frame marks, and row cadence are
integer geometric primitives. The design does not reproduce Bandai's
WonderSwan wordmark or console trade dress and does not trace, embed, or load
third-party artwork, fonts, photographs, or image-library assets.

This page records authorship and provenance. It does not make or replace a
project-wide license decision. Swan Song's inherited code and generated FPGA
output still require the separate release-clearance work documented in
[`UPSTREAMS.md`](UPSTREAMS.md) and the checked release policy.

## Design contract

Swan Wake uses the documented Analogue Pocket platform-art canvas:

- 521x165 pixels in upright display orientation;
- one big-endian-style 16-bit grayscale word per pixel, with brightness in the
  first byte and a zero second byte;
- a row-major 165x521 on-disk raster produced by rotating the upright image 90
  degrees counter-clockwise, as required for Pocket graphical assets;
- a black field, layered grayscale wake curves, and a white swan mark;
- the identifying white swan contained at display coordinates x=139..243 and
  y=26..137, conservatively within the left half of the upright canvas;
- no text, so the image does not depend on a font or imitate a trademarked
  wordmark; and
- integer-only rasterization, so host locale, time, graphics libraries, and
  floating-point implementations cannot change the output.

The live [Analogue packaging
documentation](https://www.analogue.co/developer/docs/packaging-a-core),
accessed 2026-07-14, specifies the `Platforms/_images/<platform>.bin` location,
521x165 platform image size, 16-bit grayscale representation, and 90-degree
counter-clockwise storage rotation. Platform art
belongs to the openFPGA platform surface; it does not register a Pocket
Library entry. That boundary is documented in
[`POCKET_LAUNCHER_LIBRARY.md`](POCKET_LAUNCHER_LIBRARY.md).

Analogue does not publish a platform-image safe area. As a conservative host
layout choice, the identifying swan stays in the left half of the canvas. The
retired predecessor blob is independently decodable to a nonblack bounding box
of x=131..240 and y=73..136; that known package position informed placement
only. None of its pixels or geometry are inputs to Swan Wake. The open right
side and corner marks remain subject to fresh-SD physical Pocket inspection,
because host tests cannot prove firmware clipping or composition.

The reviewed, rotated binary is 171,930 bytes and has SHA-256:

```text
0161970791a9d7913bfd1d146cb92324644607dd4a287c61d7f5a6d8e8f8045e
```

## Reproduce and inspect

The generator uses only Python's standard library and imports the logical grid
from the core-icon generator:

```sh
python3 scripts/generate_platform_art.py
python3 scripts/generate_platform_art.py --check
python3 scripts/generate_platform_art.py \
  --check --preview /tmp/swan-wake.pgm
python3 scripts/generate_platform_art_test.py
```

The focused test independently reverses the on-disk rotation, locks both the
165x521 stored raster and 521x165 upright dimensions, low bytes, palette, and
reviewed digest, proves that every white swan pixel is
an integer-scaled cell from the shared logical icon grid, compares a fresh
subprocess render byte-for-byte, rejects a same-size unrotated encoding, and
exercises stale-file rejection.
`scripts/package_validator.py` separately binds packaging to the reviewed
digest, while `scripts/package_core_test.py` proves the exact image reaches the
ZIP and rejects wrong dimensions, malformed pixel words, or changed artwork.

## Historical replacement and remaining gate

The Pocket predecessor imported a different 521x165 platform image in commit
`8aee749`. Swan Song previously retained and credited that historical image to
spiritualized1997. It is no longer part of the live distribution tree; its
exact blob identity and credit remain in repository history and
[`UPSTREAMS.md`](UPSTREAMS.md). Removing it from the current package does not
erase that provenance or alter any inherited source notice.

Host tests prove authorship inputs, deterministic bytes, format, and package
identity. They do not prove how Pocket firmware renders the art. Legibility,
centering, clipping, contrast, and presentation alongside the About text and
core icon remain explicit fresh-SD physical Pocket acceptance checks.
