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

`SwanTop` exposes ten observability outputs when its `is_simu` generic is set:
an instruction-complete pulse with `CS`, `IP`, and the wrapped 20-bit physical
PC; the register-bus write address and value; and a GPU VRAM-fetch address and
valid pulse plus a three-bit semantic role. The GPU validity tap suppresses
sound, disabled/complete screen states, inactive sprite-table DMA, and idle
sprite-tile lanes. With `is_simu = '0'`, all ten public outputs are constants;
GHDL confirms that production-generic elaboration succeeds, but Quartus resource
and timing impact remain unmeasured. These are observation points, not new
console behavior.

The Verilator adapter converts the raw taps into three event classes:

| Event | Source | Harness behavior |
| --- | --- | --- |
| `cpu` | instruction-complete pulse and CPU export state | records physical PC, `CS`, and `IP` at that boundary; an optional inclusive physical-PC range filters only this class |
| `bank` | post-mux register-bus writes | records writes to cartridge bank registers C0-C3 and de-duplicates a write level spanning adjacent system clocks |
| `vram` | GPU graphics-memory arbiter | records an aligned 16-bit internal-RAM byte address plus one of six Screen 1/2 map/tile or sprite table/tile roles for each active request |

Structured capture begins after reset is released and uses 36.864 MHz system
cycles as its timebase. New CSV and JSON Lines traces use an eight-field v2
schema with an appended role; the verifier remains able to read exact v1
seven-column CSV files without inventing missing roles. Event selection,
CPU-PC filtering, VRAM address/role filtering, output path, and format may be
supplied on the command line or in a `KEY=VALUE` config file. A build translated
without the observability ports remains usable for normal simulation, but the
harness rejects a structured-trace request rather than silently producing an
empty file. See `sim/verilator/TRACE.md` for the command-line workflow and
schema.

This instrumentation has no coverage of Pocket wrapper state, physical SDRAM,
or behavior on an Analogue Pocket. Its value for a specific game's text
renderer is established only after a trace from that title is captured and
correlated with known on-screen text.
