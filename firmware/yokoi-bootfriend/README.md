# Yokoi Boot

Yokoi Boot is the EEPROM-resident first stage for the Yokoi cartridge service.
It is a GPLv3 fork of BootFriend for WonderSwan Color and SwanCrystal. On every
normal boot it displays the approved Yokoi mark and listens on the EXT port for
a BootFriend-compatible `.bfb` RAM program. Holding Y2 selects 9600 baud;
otherwise the loader uses 38400 baud. The upstream Y1 Pocket Challenge V2 path
and Y3 hello/debug path are retained.

The build consumes the corresponding-source asset at
`assets/yokoi-logo.png` and converts it deterministically into a
64x64 stacked, four-color, 2bpp splash. The controller emblem sits above the
Yokoi wordmark for a compact boot-screen lockup. No generated or third-party
logo is substituted.

```sh
cd firmware/yokoi-bootfriend
make
make test
```

Outputs:

- `yokoi_boot.bin`: the 1920-byte custom-splash payload installed at internal
  EEPROM offset `0x80`.
- `yokoi_boot_template.bin`: pointer-template form for splash customization
  tooling.
- `build/yokoi-logo-preview.png`: nearest-neighbor preview of the exact pixels
  encoded into the boot payload.

Build the recovery-first installer ROM after the boot payload:

```sh
cd installer
make
```

This produces `installer/yokoi_boot_installer.wsc`. It backs up and verifies
the full internal EEPROM in flash-cart SRAM before installation, requires A+B
on the console, and provides a model-checked restore path. See
`installer/README.md` before using it.

After installation, the normal host workflow loads the RAM-resident cartridge
service without occupying the cartridge slot:

```sh
python3 ../yokoi-cart-service/tools/yokoi_cart.py \
  --port /dev/ttyACM0 --boot info
```

Do not write `yokoi_boot.bin` at EEPROM address zero: the first `0x80` bytes
contain the console owner's settings. Use the installer milestone or a hardware
programmer that can write the payload at offset `0x80` while preserving those
bytes. Back up the full 2048-byte internal EEPROM before installation.

This mechanism is unavailable on the original monochrome WonderSwan because it
has only a 128-byte internal EEPROM and no Color custom-splash storage area.

Yokoi Boot is a modified BootFriend version published by Regionally Famous on
2026-07-19 under GPL-3.0-or-later. See `UPSTREAM.md` and `COPYING`.
