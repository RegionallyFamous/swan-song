# Troubleshooting and Bug Reports

> Swan Song has no verified release yet. If you are using a development build,
> say so clearly and include the exact source commit and FPGA artifact identity.

## Common setup problems

### Swan Song is not in an updater

There is no verified public release yet. An updater may install or restore the
upstream WonderSwan core instead. Use only a Swan Song release explicitly
published by Regionally Famous on the official [Releases
page](https://github.com/RegionallyFamous/swan-song/releases).

### Pocket asks for a BIOS

Confirm both files exist with the exact names and sizes:

- `/Assets/wonderswan/common/bw.rom` — 4,096 bytes
- `/Assets/wonderswan/common/color.rom` — 8,192 bytes

The project does not provide or locate these files.

### A game is not listed

Confirm it is an uncompressed regular `.ws` or `.wsc` file below
`/Assets/wonderswan/common/`. Archives, symlinks, `.pc2`, and files outside the
accepted size/bank boundary are not supported.

### A compact image is rejected

Non-power-of-two images need a valid final 16-byte WonderSwan footer and
checksum. Re-dump your own cartridge or correct your own homebrew build rather
than bypassing validation.

### Swan Song is not in Analogue Library

Third-party openFPGA cores do not have a documented public API for registering
first-party Library entries. Use openFPGA, optionally with Pocket's Startup
Action and host-owned Recent category.

### A save looks wrong

Stop using the affected file and back up the entire SD card before doing more.
If you alternate between Swan Song and another WonderSwan core, remember that
the platform-common cartridge save may be shared. Do not hand-trim or rename a
save-state or EEPROM file.

## Before opening an issue

Collect:

- Swan Song release version, or exact Git commit and raw RBF/package hash;
- Pocket firmware version;
- Pocket or Dock, including controller type when relevant;
- selected System Type and all nondefault core settings;
- game orientation and whether the problem changes after a clean reset;
- whether it also occurs in the MiSTer WonderSwan core, if you can test that
  safely; and
- short, exact reproduction steps from launch to failure.

For visual or timing problems, a short Pocket/Dock capture can help. State
whether you also compared the same revision on original hardware; emulator
agreement alone does not establish the correct hardware result.

Open a [Swan Song GitHub
issue](https://github.com/RegionallyFamous/swan-song/issues) for Pocket
integration or Swan Song-specific behavior. Shared console-logic fixes should
be proposed upstream after verification, with a link back to the Swan Song
evidence.

## Protect private and copyrighted data

Never attach or upload a commercial ROM, BIOS, save, cartridge dump, private
corpus manifest, or cloud credential. Do not paste private filesystem paths or
DigitalOcean/GitHub state. Keep owner-computed commercial ROM identities in
private test evidence rather than posting them publicly, and always keep the
underlying file local.

Open and project-generated fixtures are preferred whenever they can reproduce
the problem. They make a report independently reviewable without redistributing
copyrighted data.
