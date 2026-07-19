# WonderSwan 3×3 cartridge organizer

This is a support-free, stepped display organizer for nine standard Bandai
WonderSwan cartridges. Three continuous rails hold three cartridges each, and
low divider ribs keep the cartridges aligned without covering their labels.

## Researched cartridge envelope

The model uses a nominal cartridge envelope of **65.2 mm wide × 41.8 mm high ×
6.0 mm thick**. The dimensions come from a Japanese WonderSwan hardware listing
that specifies the cassette as 41.8 × 65.2 × 6.0 mm. The Ritsumeikan Center for
Game Studies independently catalogs a physical WonderSwan cartridge at 4.1 ×
6.6 × 0.6 cm.

- [Media World WonderSwan specifications](https://mediaworld.co.jp/products/10011140001)
- [RCGS physical-package record](https://collection.rcgs.jp/page/PACKAGE0005000)

The 6.0 mm thickness is the critical fit dimension. The default rail is 6.8 mm
wide, providing 0.4 mm nominal clearance on each face. Because vintage shells,
reproduction shells, and individual FDM printers can vary, print the clearance
coupon before printing the full organizer.

## Included files

- `wonderswan-organizer-3x3.stl` — ready-to-slice nine-cartridge organizer
- `wonderswan-slot-clearance-test.stl` — small fit test with 6.4, 6.8, and
  7.2 mm channels, ordered from front to back
- `wonderswan-organizer.scad` — editable OpenSCAD source
- `generate.py` — parameterized STL and preview generator
- `wonderswan-organizer-preview.png` — rendered scale preview with cartridge
  placeholders

Default organizer dimensions: **207.6 × 57.8 × 47.0 mm**. It fits diagonally or
straight on most nominal 220 × 220 mm beds; check the slicer's printable-area
margin before starting the job.

## First test and printing

1. Print `wonderswan-slot-clearance-test.stl` base-down.
2. Try an expendable cartridge in the three channels. They are 6.4, 6.8, and
   7.2 mm from the coupon's front edge to its back edge.
3. Use the narrowest channel that inserts smoothly without scraping or bowing
   the walls.
4. If 6.8 mm fits, print the supplied organizer STL. Otherwise change
   `slot_width` in the OpenSCAD file or regenerate the STL with `--slot-width`.

Suggested starting settings:

- PLA or PETG
- 0.20 mm layer height
- 3 perimeters
- 15% gyroid or grid infill
- Base flat on the build plate
- No supports
- A 5–8 mm brim if the printer tends to lift long parts

## Regenerating the STL

The OpenSCAD source is the simplest route. For scripted generation:

```sh
python3 -m venv .venv
.venv/bin/pip install trimesh shapely mapbox-earcut manifold3d matplotlib
.venv/bin/python generate.py --columns 3 --rows 3 --slot-width 6.8
```

Changing the number of columns changes the bed-width requirement. For a common
220 mm bed, three columns is the practical maximum at full cartridge width.
