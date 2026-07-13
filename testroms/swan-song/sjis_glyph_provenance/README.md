# Shift-JIS glyph provenance fixture

This is a native, open WonderSwan Color ROM that renders `日本語かな漢` with a
small Shift-JIS lookup table. It exists to test the full Swan Song provenance
chain without a BIOS, WonderWitch image, or commercial game:

1. parse six two-byte Shift-JIS codes;
2. select licensed canonical Misaki glyph rows;
3. GDMA-copy their prepacked 2bpp tiles from ROM to internal RAM;
4. write six Screen 1 map entries from the CPU;
5. promote all 48 glyph rows through the background engine; and
6. render the expected black-on-white pixels.

The fixture does not claim to reproduce the private renderer or glyph mapping
of any commercial title. It proves that the general trace path needed to study
such a renderer works on a controlled Japanese-text workload.

The design follows WSdev's documentation of [WonderWitch Shift-JIS text],
where the renderer writes a font bitmap into the tile selected by a screen
entry, and the documented [WonderSwan 2bpp planar tile format]. The selected
font is also available from the [Misaki author's site].

[WonderWitch Shift-JIS text]: https://ws.nesdev.org/wiki/WonderWitch/FreyaBIOS/Text
[WonderSwan 2bpp planar tile format]: https://ws.nesdev.org/wiki/Display/Tile_Data
[Misaki author's site]: https://littlelimit.net/misaki.htm

## Glyph manifest

The rows are the unmodified 8×8 Misaki Gothic 2021-05-05a bitmaps. Bits run
most-significant first from left to right.

| Glyph | Unicode | Shift-JIS | Canonical rows |
| --- | --- | --- | --- |
| 日 | U+65E5 | `93 FA` | `7E 42 42 7E 42 42 7E 00` |
| 本 | U+672C | `96 7B` | `10 FE 10 38 54 BA 10 00` |
| 語 | U+8A9E | `8C EA` | `5C C8 3C D4 3E D4 DC 00` |
| か | U+304B | `82 A9` | `20 20 F4 2A 4A 48 B0 00` |
| な | U+306A | `82 C8` | `20 F4 22 44 9C 26 18 00` |
| 漢 | U+6F22 | `8A BF` | `94 7E AA 3E FE 88 B6 00` |

- Author's source page: <https://littlelimit.net/misaki.htm>
- Official PNG archive:
  <https://littlelimit.net/arc/misaki/misaki_png_2021-05-05a.zip>
- Official archive SHA-256:
  `56351ac31fa19d5dab48f0d21cbb8cf1cfb540b0de19468a40ad243d61679759`
- Pinned source mirror: <https://github.com/OpenWitch/AthenaOS> commit
  `d37beae7482616313883dcfa4bdb7114d1ef5749`, asset
  `fonts/misaki/misaki_gothic.png`
- Source PNG SHA-256:
  `99603a8569ddd673375966707278f741bff7ab39ea77c3997a0b74e1efc23dec`
- Upstream `misaki.txt` SHA-256:
  `7c1423c222f588890299c227ffe6fe0b5b249c8105980e51d6608c29796fc436`
- Author's 2021-05-05 BDF archive:
  <https://littlelimit.net/arc/misaki/misaki_bdf_2021-05-05.zip>
- BDF archive SHA-256:
  `a275f173cf5935890f84d3e65d05b1bf73028e4d4bf41cb3de0ef3b5ebe8e217`
- Full upstream `misaki_gothic.bdf` SHA-256:
  `28a8745552c844f7c73f11bdf4470225f5e08645a98c5404b2e25bb326a5cabd`
- Vendored six-record BDF subset SHA-256:
  `d4a1a4702e297dbd079119a1221bc9225164ce3f116444b50d158a04d25f58e7`
- Canonical 48-byte subset SHA-256:
  `97d6e2c5e3657f6931731db65726e4e9016432d7347db562d420d691b7754c3e`
- Packed 96-byte 2bpp subset SHA-256:
  `d53b19c215d3e3f897a810dcb6181a1f99e7fa500ee0ebc1fbf2661f2811b8f9`

The official PNG archive and pinned mirror contain byte-identical source PNGs
and notices at the hashes above. The six `STARTCHAR` records in
`misaki_gothic_subset.bdf` are copied byte-for-byte from the full upstream BDF;
the surrounding header was reduced, `CHARS` was set to six, and unrelated
glyph records were omitted. The verifier parses each record's `ENCODING`,
`BBX`, and `BITMAP` fields and independently normalizes the glyph onto the 8×8
font canvas before comparing it with the manifest above. The PNG provides a
second source hash and extraction route: it arranges JIS X 0208 rows vertically
and cells horizontally, so each Unicode scalar can be converted to JIS X 0208
and its 8×8 cell selected.

In [WonderSwan 2bpp planar order](https://ws.nesdev.org/wiki/Display/Tile_Data),
the first byte of each row is plane 0 and the second is plane 1. This fixture's
packed ROM form is deliberately `[0x00, ROW]`, so set glyph pixels use palette
index 2 and the little-endian trace word is `ROW << 8`. Palette indices 1, 2,
and 3 are red, black, and green respectively, so the pixel verifier also
detects reversed or combined plane significance. `LICENSE.misaki` records the
font's permissive redistribution terms and upstream notice; the author's
current license page is <https://littlelimit.net/font.htm>.

## Fixed layout and expected artifact

- Screen 1 map: internal RAM `0x1800`
- Glyph map cells: row 8, columns 10–15 (`0x1A14`–`0x1A1E`)
- Tile indices: 1–6
- Tile destinations: `0x2010`–`0x206F`
- Packed glyph ROM offset: `0x1FDB6` (physical `0xFFDB6`)
- Shift-JIS message ROM offset: `0x1FD52`
- ROM size: 131,072 bytes
- ROM SHA-256:
  `b199451af07c3693c7f4329a01710b4616187a73084f7fb791804855ffbe81fa`
- Frame 1 raw RGB SHA-256:
  `99b3a3ed704299c02d4ce7ecedca38746799cee6187285f94caaaf2a67832187`

The packed glyph array is explicitly two-byte aligned because the WSC general
DMA transfers words. The fixture verifier requires all 48 ordered ROM-read /
IRAM-write pairs and rejects an aliased source offset.

## Reproducible build

The build skeleton is adapted from Wonderful's
[CC0 template](https://github.com/WonderfulToolchain/target-wswan-examples/tree/811b739ab1f0203336a08da8db34365d29869617/templates/wswan).
The fixture renderer and verifier are project code; the ROM also contains the
linked Wonderful runtime covered by `LICENSE.target-wswan-syslibs`.

The checked-in ROM was built with:

```sh
docker run --rm --platform linux/amd64 \
  -v "$PWD:/work" \
  -w /work/testroms/swan-song/sjis_glyph_provenance \
  cbrzeszczot/wonderful@sha256:1bd074214c0592a5fca3f26ce0c47d3a809f48e83f68705189fe30c78e75435e \
  make clean all
```

Relevant packages in that image are `target-wswan 0.1.0-3`,
`target-wswan-syslibs 0.2.0.r253.99bf066-1`,
`toolchain-gcc-ia16-elf-gcc 6.3.0.r147156.aeca9aa010a-1`, and
`wf-tools-native 0.1.0.r180.3bf0d29-1`. The fixture Makefile enables
`-Wall -Wextra -Werror`; rebuilding produces the ROM hash above.

`make regression` runs the fixture for two frames with unfiltered
`mem,vram,bg_cell` capture. `verify_sjis_glyph_fixture.py` independently checks
the ROM identity and checksum, Shift-JIS and glyph offsets, 48 GDMA word
transfers (48 ROM reads paired with 48 IRAM writes), six exact CPU map writers,
two complete promotions of every glyph row, exact ROM source offsets,
collision-free writer snapshots, and every final RGB pixel.
