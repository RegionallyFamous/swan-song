# WSC extended display-range fixture

`tile_screen_extended_range.wsc` is an open test ROM from Adrian "asie"
Siekierka's `ws-test-suite`. It verifies that 2bpp Color mode can use the
extended screen-map, tile-bank, and sprite-table address bits.

## Provenance

- Source: <https://github.com/asiekierka/ws-test-suite>
- Source commit: `7dfa0e2e869d08386b685d6a56df0bcfaf181b47`
- Source path: `src/color/display/tile_screen_extended_range`
- Build container: `cbrzeszczot/wonderful@sha256:1bd074214c0592a5fca3f26ce0c47d3a809f48e83f68705189fe30c78e75435e`
- `target-wswan-syslibs`: `0.2.0.r253.99bf066-1` (`99bf066`, zlib license)
- ROM size: 131,072 bytes
- ROM SHA-256: `72bf0fca0b6e7d3a61cb8c93c7675b4c1ac4e744b39f64ecf63ee3095aaf4346`

A clean checkout at that commit, built in the pinned container with the
repository `Makefile`, reproduced the checked-in ROM byte for byte. `main.c`
and `wfconfig.toml` are copied beside the ROM for direct audit; the complete
build inputs remain at the pinned source commit.

The test-suite MIT notice is in `LICENSE.ws-test-suite`. The linked Wonderful
runtime/system libraries use the zlib notice in
`LICENSE.target-wswan-syslibs`. No BIOS or commercial software is included.
