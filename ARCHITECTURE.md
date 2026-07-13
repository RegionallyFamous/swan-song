# Swan Song architecture map

This map describes the pinned Pocket baseline at `073213a2` and MiSTer reference at
`8f7a4d67`. It is a source-level map; it does not claim behavior on an Analogue
Pocket.

## Module hierarchy

```text
apf_top (APF pins and bridge)
└── core_top (Pocket integration)
    ├── core_bridge_cmd (host commands, RTC, data-table, Memories protocol)
    ├── data_loader ×3 (cartridge, BIOS, nonvolatile save)
    ├── data_unloader (nonvolatile save reads)
    ├── save_state_controller (APF Memories ↔ MiSTer save-state bus)
    ├── mf_pllbase (74.25 MHz → core/memory/video clocks)
    ├── wonderswan (system wrapper and frame delivery)
    │   ├── sdram (cartridge ROM and external SRAM)
    │   ├── SwanTop (WonderSwan system)
    │   │   ├── cpu (V30MZ-compatible CPU)
    │   │   ├── memorymux (RAM, BIOS overlay, cart banks, EEPROM)
    │   │   ├── gpu
    │   │   │   ├── gpu_bg ×2
    │   │   │   └── sprites
    │   │   ├── dma
    │   │   ├── IRQ
    │   │   ├── joypad
    │   │   ├── sound (five channel submodules)
    │   │   ├── rtc
    │   │   ├── savestates
    │   │   └── statemanager
    │   └── three 224×144 RGB444 frame stores
    └── sound_i2s
```

`apf_top` and the APF support files are framework plumbing. `core_top` is the
Pocket-specific control/data boundary. `wonderswan.sv` adapts the MiSTer system
to Pocket memory, controls, video timing, and settings. `rtl/SwanTop.vhd` and
the VHDL below it are the console implementation.

## Clock domains

| Domain | Frequency | Main responsibility |
| --- | ---: | --- |
| `clk_74a` | 74.25 MHz input | APF bridge, command handler, data-slot ingress, I²S transport |
| `clk_74b` | 74.25 MHz input | Present at the APF boundary; unused by this core |
| `clk_sys_36_864` | 36.864 MHz | SwanTop, CPU/PPU clock enables, framebuffer writer/reader, output timing |
| `clk_mem_110_592` | 110.592 MHz | SDRAM controller, ROM/save ingress, external EEPROM port |
| `clk_vid_3_75` | 6.144 MHz | Pocket RGB interface |
| `clk_vid_3_75_90deg` | 6.144 MHz, 90° shifted | Pocket RGB interface phase clock |

The `clk_vid_3_75` names are historical and do not describe the configured
frequency; `mf_pllbase_0002.v` is authoritative for the 6.144 MHz outputs. The
constraints put the related memory/system PLL outputs in one group and declare
that group, the bridge clock, both 74.25 MHz inputs, and each video output
asynchronous to one another. `data_loader`, `data_unloader`,
`save_state_controller`, and `synch_3` instances implement several of the
explicit clock-domain crossings.

Inside `SwanTop`, 36.864 MHz is divided with clock enables to recreate the
3.072 MHz machine rate and 12.288 MHz memory cadence. Fast-forward changes
enable cadence rather than the FPGA clock.

## Video path

`gpu.vhd` produces linear 224×144 RGB444 pixels (`pixel_out_addr`,
`pixel_out_data`, `pixel_out_we`). `wonderswan.sv` always writes those pixels
to one of three 32,256-pixel arrays. With buffering disabled it continually
reads bank zero; with triple buffering/flicker blend enabled it rotates banks
on address 32,255.

The same wrapper generates the outgoing 60 Hz-compatible raster. Because its
terminal-count comparisons are inclusive, the default path uses 401 horizontal
pixel-enable periods at a `/6` divider (about 59.39 Hz over 258 lines); the
dormant native-rate path uses 379 periods at `/5` (about 75.40 Hz). Frame-bank
rotation is enabled by `use_triple_buffer` or by bit 1 of
`configured_flickerblend`; consequently, the two-frame blend setting relies on
triple buffering also being enabled, while the three-frame setting enables the
banks itself. Rotation is not performed in RTL: `core_top` writes an orientation
flag into the blanking stream and APF selects scaler mode 0 or 1 from
`video.json`.

## Data slots and memory map

| Slot | APF ID | Bridge region | Destination |
| --- | ---: | --- | --- |
| Cartridge | 0 | `0x1.......` | Pocket SDRAM channel 1 |
| B&W BIOS | 9 | `0x3.......` | 4 KiB inferred BIOS RAM in `memorymux` |
| Color BIOS | 10 | `0x3.......` | 8 KiB inferred BIOS RAM in `memorymux` |
| Save | 11 | `0x2.......` | external SRAM in SDRAM or EEPROM BRAM; RTC data follows save payload |
| APF Memory | command protocol | `0x4.......` | `save_state_controller` and MiSTer state bus |

`src/support/chip32.asm` detects `.wsc`, sequences cartridge/BIOS/save loading,
and starts the core. The wrapper also reads cartridge metadata from the image
footer. Extension detection and the footer color flag contribute to automatic
color mode; footer fields provide the mapper/RAM type, ROM mask, RTC flag, and
save size. Save size is written back to the APF data table at runtime. The
current Pocket wrapper does not honor the footer RTC flag: `has_rtc` is tied
high, so the data table always reserves 12 trailing RTC bytes.

`core.json` names that Chip32 program as `chip32.bin`; it is a required package
dependency even though the source repository carries only its assembly and a
canonical encoded build image. `package_core.py` materializes the verified
259-byte binary under that declared name. It does not fetch code during a build.

No BIOS or commercial cartridge image is part of this repository.

## Controls and rotation

`core_top` synchronizes the Pocket controller bitmap into the system domain.
`wonderswan.sv` changes the A/B/face/trigger mapping when the console's
`vertical` signal is active. The D-pad always feeds X1–X4. APF scaler rotation
is selected independently from `configured_orientation`; this separation is a
key Phase 2 audit point because forced display rotation and gameplay remapping
can currently disagree.

## Simulation boundary

The executable regression flow translates the production `SwanTop` VHDL
hierarchy through pinned GHDL 6.0.0, substitutes a behavioral dual-port RAM for
Intel's `altsyncram`, and compiles the result with Verilator. It does not
simulate the Pocket-facing `core_top`/`wonderswan.sv` wrappers or physical SDRAM
controller. Its C++ harness models cartridge ROM reads and a zero-initialized
1 MiB external SRAM with byte-enable writes, programs BIOS RAM, captures the
GPU's direct RGB444 framebuffer stream, and optionally writes either a
whole-design VCD or a filtered structured event trace. With no BIOS argument it
uses a nine-byte simulation-only bootstrap that disables the BIOS overlay and
jumps through the cartridge reset vector.

### Simulation observability

`SwanTop` exposes 39 observability outputs when its `is_simu` generic is set.
They carry completed-instruction location; accepted mapper-write identity;
completion-aligned display reads and mixed-port collision status; promoted
Screen 1/2 background-cell metadata; and completed CPU/GDMA/SDMA transactions
with resolved memory space, backing offset, and exact CPU origin where the CPU
can prove one. With `is_simu = '0'`, all public debug outputs are constants;
the checked-in translated-model regression exercises `is_simu = '1'`, so
production-generic GHDL elaboration and Quartus resource/timing impact are not
part of the current automated gate. These are observation points, not evidence
of Pocket hardware behavior.

The Verilator adapter converts the raw taps into five event classes:

| Event | Source | Harness behavior |
| --- | --- | --- |
| `cpu` | instruction-complete pulse and CPU export state | records physical PC, `CS`, and `IP` at that boundary; an optional union of inclusive physical-PC ranges filters only this class |
| `bank` | accepted CPU register-bus writes, excluding reset/savestate overrides | records byte commits to cartridge bank registers C0-C3 with the exact owning instruction ID and first-byte PC |
| `vram` | GPU unified-IRAM arbiter | records each completed aligned 16-bit display read, returned word, collision flag, and one of six Screen 1/2 map/tile or sprite table/tile roles; physical background prefetches remain visible while a layer is disabled |
| `mem` | completed system-memory bridge | records CPU, GDMA, and SDMA reads/writes with raw address/value/lane mask, resolved space/offset, and exact, unattributed, or inapplicable CPU origin status |
| `bg_cell` | Screen 1/2 background promotion boundary | binds one decoded map word to the exact 2bpp/4bpp row entering a pixel buffer, including tile mode, flips, palette, coordinates, contributing bytes, and collisions; it is not a final-compositor visibility claim |

Structured capture begins after reset is released and uses 36.864 MHz system
cycles as its timebase. New CSV and JSON Lines traces use the 36-field v5
schema; the CSV verifier retains exact v1-v4 compatibility without inventing
fields absent from those legacy headers. Command-line or `KEY=VALUE` config
filters can independently select events, CPU PCs, display addresses/roles, and
memory initiators/accesses/addresses/spaces/offsets/origins. Each successful
capture writes a manifest that binds its ROM/boot inputs, filters, reset start,
requested termination, and completeness claims. A build translated without
the observability ports remains usable for normal simulation, but the harness
rejects a structured-trace request rather than silently producing an empty
file. See `sim/verilator/TRACE.md` for the exact schema and workflow.

This instrumentation has no coverage of Pocket wrapper state, physical SDRAM,
or behavior on an Analogue Pocket. Its value for a specific game's text
renderer is established only after a trace from that title is captured and
correlated with known on-screen text.
