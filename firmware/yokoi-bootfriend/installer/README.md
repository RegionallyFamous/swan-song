# Yokoi Boot installer

This ROM installs `yokoi_boot.bin` into a WonderSwan Color or SwanCrystal's
internal EEPROM. It requires a flash cartridge with at least 8 KiB of SRAM.
Before changing the splash area it writes a full 2048-byte, model-tagged,
CRC-verified EEPROM backup into that SRAM.

Installation requires an A+B chord on the console. The custom splash is
disabled before programming and enabled only after a full word-for-word
verification. SwanCrystal factory TFT calibration bytes and the first 128
bytes of owner/settings data are not replaced. The restore path requires the
stronger Y1+Y3+A chord and accepts only a CRC-valid backup made on the same
console model.

```sh
cd firmware/yokoi-bootfriend
make
cd installer
make
```

Flash `yokoi_boot_installer.wsc` to a compatible flash cartridge, boot it,
and follow the on-console menu. Keep the flash cartridge unchanged until the
installation has been hardware-tested and its backup copied elsewhere.
