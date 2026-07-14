# WonderSwan internal-EEPROM fixture

`internal.ws` is the open `mono/eeprom/internal` test from Adrian "asie"
Siekierka's `ws-test-suite`. Its mono-hardware path checks the internal EEPROM
data and command ports, write/erase behavior, status flags, write lock and
unlock, invalid commands, protected data, and the internal-controller DONE
bit behavior.

## Pinned provenance

- Source: <https://github.com/asiekierka/ws-test-suite>
- Source commit: `7dfa0e2e869d08386b685d6a56df0bcfaf181b47`
- Source path: `src/mono/eeprom/internal`
- `main.c` SHA-256: `99a1fc1341dcc4a6c7e72fa70d5e029e74a0f2a181a0ea251781525a8c91e598`
- `wfconfig.toml` SHA-256: `f82d4feb8d593407aad77ecffffc206861d6848c52b7495fb06400b6c419e088`
- Build container: `cbrzeszczot/wonderful@sha256:1bd074214c0592a5fca3f26ce0c47d3a809f48e83f68705189fe30c78e75435e`
- `target-wswan-syslibs`: `0.2.0.r253.99bf066-1` (`99bf066`, zlib license)
- ROM size: 131,072 bytes
- ROM SHA-256: `2e5c611fe7278703a810e7219c6cda7ecc25254bd9ff2b4c81650d78c73213db`
- ROM checksum: stored and recomputed 16-bit sum `0x5027`
- Final 16 footer bytes: `ea0000c6fe0000000000000004012750`
- Embedded font: offset `0x1e860`, 1,024 bytes, SHA-256
  `55aded7d9763f138df6f13bd4057381243bc45cf8c009e79db982282e3e6294b`

A clean checkout at the pinned commit reproduces the checked-in ROM with:

```sh
docker run --rm --platform linux/amd64 \
  --mount type=bind,src="$PWD",dst=/work \
  --workdir /work \
  cbrzeszczot/wonderful@sha256:1bd074214c0592a5fca3f26ce0c47d3a809f48e83f68705189fe30c78e75435e \
  make build/roms/mono/eeprom/internal.ws
```

The exact test source and cartridge configuration are copied beside the ROM.
The test-suite MIT notice is in `LICENSE.ws-test-suite`; linked Wonderful
system libraries use `LICENSE.target-wswan-syslibs`. No BIOS, commercial ROM,
or proprietary firmware is included.

## Strict mono-hardware acceptance target

The dedicated verifier describes the target, not the current implementation.
It binds the exact source, licenses, ROM, reset/header footer, additive ROM
checksum, embedded font, and six-frame trace manifest. Two captures must have
byte-identical CPU/background traces and final framebuffers. Each capture must
remain in the terminal loop at physical PC `0xff620` and show all 23
source-defined mono-hardware result markers as tile 5, with no tile 6 at any
result position and a complete post-terminal raster for every marker.

The exact target frame is reconstructed from the bound ROM font, the source's
labels and successful read/write values, and the deterministic simulator's
default protected internal-EEPROM value `0x1921`. Its 224x144 RGB SHA-256 is
`830503147842b803d26b707675009e6b8e3b0faa1ee3ad1aef15c3e9e74e444d`.
The manifest target is reset-release capture, 2,887,553 cycles, six completed
frames, the default 4-KiB mono BIOS identity, zeroed initial IRAM, and complete
CPU/background history with no trace filters.

## Current translated-RTL result: accepted

Two independent current-code captures are byte-identical, remain in the
terminal loop, and pass all **23 of 23** mono-hardware result positions. The
strict verifier reports 184 complete PASS-tile rows, a terminal tail of 36,267
CPU rows, and the target final RGB SHA-256
`830503147842b803d26b707675009e6b8e3b0faa1ee3ad1aef15c3e9e74e444d`.
The paired trace SHA-256 is
`f134c4255f3aafd90b846620190a7db6428d3130febff20042ad749d99573b57`.
A focused controller bench separately covers data-latch isolation, EWDS/EWEN,
WRAL/ERAL, protected/user regions, invalid controls, DONE/READY transitions,
and restoration of a saved disabled-write latch. The deterministic ten-enable
READ busy window is an emulator-conservative functional delay, not a physical
timing claim.

## Color-hardware mono-mode limitation

The ROM has a mono cartridge header. The current simulator therefore exposes
mono hardware, so the source's `ws_system_color_active()` branch does not run.
That branch contains four additional assertions across `Mono read`, `Mono
w.lock`, and `Mono w.unlock` rows. Exercising them requires a deliberate model
override that presents Color hardware while booting this mono fixture.

The 23-marker target covers only the source-defined mono-hardware path. It
must not be cited as evidence for Color-hardware mono-mode EEPROM reads or
Color-to-mono lock/unlock compatibility. It also does not establish physical
write latency, persistence across power cycles, undocumented commands beyond
the tested set, or Analogue Pocket hardware timing.
