# WonderSwan SoC interrupt fixture

`interrupts.ws` is the open `mono/soc/interrupts` test from Adrian "asie"
Siekierka's `ws-test-suite`. It exercises the UART-send-ready level interrupt
and the interrupt controller's status, acknowledgement, vector-base masking,
pending-vector retention, and highest-priority selection behavior.

## Pinned provenance

- Source: <https://github.com/asiekierka/ws-test-suite>
- Source commit: `7dfa0e2e869d08386b685d6a56df0bcfaf181b47`
- Source path: `src/mono/soc/interrupts`
- `main.c` SHA-256: `4d30892baac71cbcba96f858ae76db4c5cba8768030416f551ee89328707bbce`
- `wfconfig.toml` SHA-256: `f82d4feb8d593407aad77ecffffc206861d6848c52b7495fb06400b6c419e088`
- Shared `common/test/pass_fail.h` SHA-256: `58069f6bafe1bed3a143c5b95cafb25d878e781b8b2ad3c2aef44667ff9d24fe`
- Shared `common/text.c` SHA-256: `091f384e7de483ef170a397b3b33bfa3e01a477a3a4a0256fa605a5bf7c2ec73`
- Shared `common/text.h` SHA-256: `a4379649b73d2732b46fc5f83d0ffca8c594199c2cc41c4fca4a64960bc89ff3`
- Shared `resources/font_ascii.bin` SHA-256: `55aded7d9763f138df6f13bd4057381243bc45cf8c009e79db982282e3e6294b`
- Build container: `cbrzeszczot/wonderful@sha256:1bd074214c0592a5fca3f26ce0c47d3a809f48e83f68705189fe30c78e75435e`
- `target-wswan-syslibs`: `0.2.0.r253.99bf066-1` (`99bf066`, zlib license)
- ROM size: 131,072 bytes
- ROM SHA-256: `d8a4da6d6c33ad3f58e9bb9b105135788f832544db1b85f8f0e66e227d847da0`
- ROM checksum: stored and recomputed 16-bit sum `0xf900`
- Final 16 footer bytes: `ea000018ff00000000000000040100f9`

A clean checkout at the pinned commit reproduces the ROM with:

```sh
docker run --rm --platform linux/amd64 \
  --mount type=bind,src="$PWD",dst=/work \
  --workdir /work \
  cbrzeszczot/wonderful@sha256:1bd074214c0592a5fca3f26ce0c47d3a809f48e83f68705189fe30c78e75435e \
  make build/roms/mono/soc/interrupts.ws
```

The exact test source and cartridge configuration are copied beside the ROM
for audit. The test-suite MIT notice is in `LICENSE.ws-test-suite`; linked
Wonderful system libraries use `LICENSE.target-wswan-syslibs`. No BIOS,
commercial ROM, or proprietary firmware is included.

## Simulation acceptance

A strict translated-RTL regression should bind this exact ROM and source,
reach the terminal self-loop at physical PC `0xff684`, and require all thirteen
result markers to be PASS: row 0 columns 20 through 27 and row 1 columns 23
through 27. Repeated complete captures should have byte-identical traces and
framebuffers.

The fixture establishes only the behavior it directly checks. It does not
exercise UART receive or serialized transmit data, keypress or cartridge IRQs,
CPU interrupt-handler dispatch, Color-specific behavior, or exact interrupt
latency. Those properties require separate stimuli and must not be inferred
from a passing frame.
