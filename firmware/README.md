# Yokoi WonderSwan hardware support

This directory contains the complete preferred source for the two separately
executable WonderSwan programs used by SwanSong Desktop's Cartridge Lab:

- `yokoi-bootfriend`: a GPL-3.0-or-later BootFriend fork, recovery-first
  internal-EEPROM installer, deterministic logo converter, tests, and exact
  upstream provenance;
- `yokoi-cart-service`: a GPL-3.0-or-later RAM-resident cartridge reader and
  guarded save-memory writer, its documented serial protocol, host reference
  client, and tests.

These programs are separate from the FPGA core. See the directory-local
licenses and the repository's `LICENSING.md` component map.

## Build and verify

Install NASM, Python 3 with Pillow, and the Wonderful Toolchain at
`/opt/wonderful`, then run:

```sh
make -C firmware/yokoi-bootfriend test
make -C firmware/yokoi-bootfriend/installer
make -C firmware/yokoi-cart-service
make -C firmware/yokoi-cart-service test
```

The `0.2.0-prototype.1` source publication produces the two artifacts pinned by
SwanSong Desktop:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `yokoi_boot_installer.wsc` | 131072 | `8a2d6e580ebb0bc53b52929166d9517e90840db39849804717880439682db8f3` |
| `yokoi-cart-service.bfb` | 4484 | `b650bc62ddbbec6027783b577baee5319ffd25d25ce06d38c1353174dc0d1ce0` |

Those hashes were reproduced from a clean source tree before publication.
Automated protocol and build checks do not substitute for physical
WonderSwan, cartridge, adapter, and recovery testing.
