# WonderSwan Color Sound-DMA fixture

`sound_dma.wsc` is the open `color/dma/sound_dma` test from Adrian "asie"
Siekierka's `ws-test-suite`. It exercises the 20-bit Sound-DMA registers,
repeat reads from ROM and internal RAM, hold behavior, terminal register
values, 20-bit source wrap, and delivery of the final byte.

## Pinned provenance

- Source: <https://github.com/asiekierka/ws-test-suite>
- Source commit: `7dfa0e2e869d08386b685d6a56df0bcfaf181b47`
- Source path: `src/color/dma/sound_dma`
- `main.c` SHA-256: `aed792acdf685e09668d324a857e344039b1f54ddc7fd33bb1a3f493187955a5`
- `wfconfig.toml` SHA-256: `ccf7a81c479c07d617f15ba58c3d2c5b3a1a35f794ebb39501e35a955f1197b3`
- Build container: `cbrzeszczot/wonderful@sha256:1bd074214c0592a5fca3f26ce0c47d3a809f48e83f68705189fe30c78e75435e`
- `target-wswan-syslibs`: `0.2.0.r253.99bf066-1` (`99bf066`, zlib license)
- ROM size: 131,072 bytes
- ROM SHA-256: `89b57284c70d24837b686153cff99b6e4332d3682f001bc6209d0da3a4c1333f`
- ROM checksum: stored and recomputed 16-bit sum `0x7bcb`
- Final 16 footer bytes: `ea0000d9fe000001000000010401cb7b`
- Embedded font: offset `0x1e990`, 1,024 bytes, SHA-256
  `55aded7d9763f138df6f13bd4057381243bc45cf8c009e79db982282e3e6294b`

A clean checkout at the pinned commit reproduces the checked-in ROM with:

```sh
docker run --rm --platform linux/amd64 \
  --mount type=bind,src="$PWD",dst=/work \
  --workdir /work \
  cbrzeszczot/wonderful@sha256:1bd074214c0592a5fca3f26ce0c47d3a809f48e83f68705189fe30c78e75435e \
  make build/roms/color/dma/sound_dma.wsc
```

The exact test source and cartridge configuration are copied beside the ROM.
The test-suite MIT notice is in `LICENSE.ws-test-suite`; linked Wonderful
system libraries use `LICENSE.target-wswan-syslibs`. No BIOS, commercial ROM,
or proprietary firmware is included.

## Important `.sram` toolchain limitation

The pinned container compiled `sample_data_sram` from the source's `.sram`
section at offset `0x0059` in **segment zero**. Consequently, both tests whose
screen labels say `slow SRAM` and `fast SRAM` actually issue Sound-DMA reads
to IRAM addresses `0x0059` through `0x0068`. The strict trace contract exposes
43 such rows as `source_labeled_sram_iram_rows=43` and requires
`actual_sram_rows=0`.

Those two green markers therefore do not establish cartridge-SRAM access,
SRAM mapping, or slow/fast SRAM wait-state behavior. The labels describe the
upstream source's intention, not what this particular Wonderful build placed
on the bus. A separate fixture with a verified nonzero SRAM segment is needed
before claiming physical SRAM coverage.

## Simulation acceptance and scope

`make regression` performs two independent 15-frame captures from reset
release with the default deterministic Color BIOS, complete CPU/background
history, and memory filtered only to the Sound-DMA initiator. The manifest is
bound to 7,280,513 cycles, 15 completed frames, the exact ROM and BIOS
identities, zeroed initial IRAM, and the exact event/filter configuration.

The dedicated verifier requires:

- exactly 346 Sound-DMA reads in the expected functional sequence;
- exact `sdma` initiator, read access, byte-enable mask `3`, address, resolved
  space, mapped offset, value, and `not_applicable` origin provenance for every
  row;
- all 22 tile-5 PASS markers at their source-defined positions, no tile-6
  result at those positions, and a complete post-terminal raster for each;
- an uninterrupted terminal-loop tail at physical PC `0xff63a`; and
- the exact final 224x144 RGB framebuffer SHA-256
  `b4166e27c8d6c686b854e4bddb9816e967c9a406afe2886d128abf1059ca927a`.

The two complete CSV traces and final framebuffers must be byte-identical. A
recorded reference run produced trace SHA-256
`4488231b2b0d49cdffbe3a0a4ddf8d87c18f9f4ef7fa3d6340874d83f39cf627`.
That trace digest records determinism evidence; acceptance is based on the
field-by-field contract rather than treating one opaque trace hash as proof.

This fixture establishes only those visible assertions and functional bus
reads. It does not establish exact transfer cadence, CPU-steal duration,
cartridge-SRAM behavior, every slower rate, arbitrary source mappings, Hyper
Voice behavior, save-state continuation, or Analogue Pocket hardware timing.
