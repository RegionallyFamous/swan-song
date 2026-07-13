# WonderWitch/AthenaOS hello fixture

This source-only fixture proves the read-only WonderWitch path that current
Wonderful actually ships: compile a `wwitch` program to `.fx`, assemble it
with the open clean-room AthenaOS into a normal `.ws` image, and boot that
image in Swan Song's translated system model. The program calls WonderWitch
BIOS services to initialize text, renders `Hello, World!`, and waits for Start.

No BIOS, firmware image, `.fx`, or assembled `.ws` is checked into Swan Song.
The generated files live under the ignored root `build/` directory. This keeps
the project brief's no-BIOS-bundling rule while still making the compatibility
result reproducible for a developer who installs the public Wonderful package.

The fixture is adapted from the CC0
[Wonderful `wwitch` template](https://github.com/WonderfulToolchain/target-wswan-examples/tree/811b739ab1f0203336a08da8db34365d29869617/wwitch).
The generated ROM uses the MIT-licensed
[AthenaOS](https://github.com/OpenWitch/AthenaOS/tree/d37beae7482616313883dcfa4bdb7114d1ef5749)
package. The adjacent license is attribution for the external build input; it
does not turn the generated firmware into a repository artifact.

## Reproduce

Install Wonderful and its pinned clean-room firmware package:

```sh
/opt/wonderful/bin/wf-pacman -S target-wswan target-wswan-athenaos
scripts/validate_wonderwitch_athena.sh
```

The validator intentionally requires the exact recorded packages:

| Package | Version |
| --- | --- |
| `target-wswan` | `0.1.0-3` |
| `target-wswan-syslibs` | `0.2.0.r254.d7d97ce-1` |
| `target-wswan-athenaos` | `0.2.0.r173.d37beae-1` |
| `toolchain-gcc-ia16-elf-binutils` | `2.43.1.r119451.5cc0e071551-1` |
| `toolchain-gcc-ia16-elf-gcc` | `6.3.0.r147159.e7507d1845e-1` |
| `toolchain-gcc-ia16-elf-gcc-libs` | `6.3.0.r147159.e7507d1845e-1` |
| `wf-tools` | `0.2.0-3` |
| `wf-tools-lua` | `0.1.0.r181.7f5f3f9-1` |

Wonderful currently stamps `.fx` headers with wall-clock time. The fixture's
small normalizer replaces only that four-byte field with the pinned AthenaOS
commit date before `wf-wwitchtool mkrom`, making two clean builds identical.

Recorded outputs:

- deterministic `.fx`: 480 bytes, SHA-256
  `d513b42f8e72bb9a45db2b800adb0411268fe8038fef58bea935c6ee54dff361`;
- deterministic AthenaOS `.ws`: 262,144 bytes, SHA-256
  `bb190b7cbbd0a8485b689159bcc5196c252ef0da88412453d4059dda0add83ae`;
- frames 0-2: blank raw RGB SHA-256
  `b404fb94d84fa4bd527d8eabaf2d13393f5c43f03d838c4aa2a8c95855aef511`;
- frames 3-4: stable visible output raw RGB SHA-256
  `d4e4995f9df957734f3ccad96ee1fa5c1dd1570a443692a0590c479ec76e9814`;
- visible frame census: 32,018 white and 238 black pixels; and
- the filtered CPU trace enters the ROM filesystem executable at physical
  `DFE80h`, reaches `main` at `DFF2Eh`, calls the text service, and settles in
  the `key_wait` loop at `DFF42h`/`DFF44h`.

This verifies read-only `mkrom` boot and a real WonderWitch BIOS-call workload
in the translated core. It does not verify Pocket timing, direct `.fx` loading,
writable `rom0`, a physical WonderWitch cartridge, port `CEh`, or flash command
state. See [`WONDERWITCH_VALIDATION.md`](../../../WONDERWITCH_VALIDATION.md).
