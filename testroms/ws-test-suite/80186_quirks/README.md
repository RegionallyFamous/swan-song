# 80186-compatible V30MZ quirk fixture

This is the open `mono/cpu/80186_quirks` test from Adrian "asie"
Siekierka's `ws-test-suite`. It checks the V30MZ behavior of AAM and AAD
with a non-decimal base and the undocumented SALC opcode.

## Pinned provenance

- Source: <https://github.com/asiekierka/ws-test-suite>
- Source commit: `7dfa0e2e869d08386b685d6a56df0bcfaf181b47`
- Source path: `src/mono/cpu/80186_quirks`
- Build container: `cbrzeszczot/wonderful@sha256:1bd074214c0592a5fca3f26ce0c47d3a809f48e83f68705189fe30c78e75435e`
- `target-wswan-syslibs`: `0.2.0.r253.99bf066-1` (`99bf066`, zlib license)
- ROM size: 131,072 bytes
- ROM SHA-256: `b44090665f0165c7e3279da13359a0b27c69e3127823d55b2bb16f3dd4a2eb1c`

A clean checkout at that commit, built with the same pinned Wonderful image
as the repository's extended-range fixture, reproduced this ROM. The exact
source and cartridge configuration are copied beside it for audit. The
test-suite MIT notice is in `LICENSE.ws-test-suite`; linked Wonderful system
libraries use `LICENSE.target-wswan-syslibs`. No BIOS or commercial software
is included.

## Regression acceptance

`make regression` runs this ROM twice through the translated RTL and requires
byte-identical CPU/background traces and framebuffers. The strict verifier
binds the files and ROM footer/font, requires a stable terminal loop plus all
24 promoted rows of the three PASS markers, and reconstructs the exact final
frame. The accepted `frame-1.rgb` SHA-256 is
`871d7e2de2f915ceaae2a94fcf99b86825430f79588e43e640f9bfa8fed6dce0`.

The upstream fixture contains exactly three result-value tests: AAM base 16,
AAD base 16, and SALC with carry clear/set. It does not test arithmetic flags,
AAM base-zero interrupt behavior, data-memory side effects, or instruction
timing; those properties must not be presented as hardware-proven by this ROM.
