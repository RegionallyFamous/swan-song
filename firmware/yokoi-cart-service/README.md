# Yokoi Cart Service

Yokoi Cart Service turns a WonderSwan Color or SwanCrystal into a cartridge
reader and a guarded save-memory writer. It runs entirely from internal RAM,
leaving the cartridge slot available for the cartridge being serviced.

Version 0.2 can report the footer, dump ROM, dump SRAM or cartridge EEPROM,
and restore SRAM/EEPROM save images. Retail game ROM is mask ROM and cannot be
rewritten. Flash-cartridge ROM programming remains disabled until individual
flash command sets and boards can be identified and verified safely.

## Architecture

1. Yokoi Boot's EEPROM splash loader listens on the EXT serial port.
2. The host sends `yokoi-cart-service.bfb` into internal RAM with checksum-mode
   XMODEM.
3. The service switches to a framed CRC-16 protocol at 38400 baud.
4. The PC can inspect/dump the cart or request a save restore.

`tools/yokoi_cart.py --boot` performs steps 2 and 3 in one command. The service
supports BootFriend as well as Yokoi Boot because the `.bfb` transport remains
compatible.

## Write safety

A save restore is accepted only when all of these checks pass:

- footer save kind and exact image size match;
- the host confirms by typing `WRITE` (unless its explicit override flag is
  used);
- the user physically holds A+B on the console while the arm packet arrives;
- the cartridge fingerprint is unchanged before arming and before every chunk;
- chunks arrive sequentially and are immediately read back;
- the device's rolling CRC32 matches the proposed image;
- the host performs a second, full save-memory readback and byte comparison.

Any cart swap, unrelated command, bad sequence, timeout at the host, EEPROM
write failure, or readback mismatch cancels the write session. No packet can
enable the cartridge self-flash port, and the ROM-flash commands remain locked.

## Build and test

```sh
cd firmware/yokoi-cart-service
make
make test
```

The output is `yokoi-cart-service.bfb`.

## Hardware use

Use an ExtFriend-compatible 3.3 V WonderSwan EXT-to-USB adapter. Never connect
the EXT pins directly to a PC RS-232 port; its voltage and polarity are not
compatible.

```sh
python3 -m pip install pyserial

# Power on with Yokoi Boot installed, then load the service and inspect the cart.
python3 tools/yokoi_cart.py --port /dev/ttyACM0 --boot info

# For later commands in the same powered session, omit --boot.
python3 tools/yokoi_cart.py --port /dev/ttyACM0 dump-rom cartridge.wsc
python3 tools/yokoi_cart.py --port /dev/ttyACM0 dump-save cartridge.sav
python3 tools/yokoi_cart.py --port /dev/ttyACM0 restore-save restored.sav
```

The host refuses to overwrite existing dump files. A restore never skips the
physical A+B confirmation, even when `--yes-really-write` skips the host's
typed confirmation.

This is not an original monochrome WonderSwan bootstrap. That model lacks the
Color system's 2 KiB custom-splash EEPROM area and needs a separate entry path.

## Prior art and licensing

The execution model and mapper behavior were informed by the GPLv3+
[ws-backup-tool](https://github.com/asiekierka/ws-backup-tool),
[BootFriend](https://github.com/asiekierka/ws-bootfriend),
[ExtFriend](https://github.com/WonderfulToolchain/ws-extfriend), the Wonderful
Toolchain headers, and the WSdev hardware documentation. Yokoi Cart Service
uses its own framed protocol and write-session safety contract.

Firmware and host code in this directory are GPL-3.0-or-later; see `COPYING`.
The Makefile is based on the CC0 Wonderful Toolchain project template.
Regionally Famous first published this implementation on 2026-07-19.
