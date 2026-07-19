# WonderWitch WWTM SDK overlay

This is a narrow compatibility overlay for Wonderful Toolchain's experimental
`wwitch` target. It corrects four header-level defects confirmed by the 2001
*Wonder Witch Technical Manual* register tables and by the matching AthenaBIOS
handlers:

- `sram_set_map()`, `rom0_set_map()`, and `rom1_set_map()` now call
  `bank_set_map()` instead of passing an impossible second argument to
  `bank_get_map()`;
- `bank_read_word()` returns the complete 16-bit AX value;
- `sys_get_tick_count()` returns the complete 32-bit DX:AX value; and
- `LCD_SLEEP_OFF` is `0` and `LCD_SLEEP_ON` is `1`, so the existing `lcd_on()`
  and `lcd_off()` helpers operate in the direction their names promise.

The overlay deliberately does not change manual claims that conflict with the
open firmware implementation. In particular, AthenaBIOS confirms the current
SDK's numeric-alignment flag, text-mode return register, RTC service ordering,
and LCD-orientation bits. Those manual discrepancies are documented in the
translation instead of being turned into speculative code changes.

## Use it

Put this include directory before Wonderful's own target include directory.
For the standard Wonderful Makefile template:

```make
INCLUDEDIRS := /absolute/path/to/Yokoi/sdk/wonderwitch-wwtm/include include
```

Existing source can continue to include `<sys/bios.h>`, `<sys/bank.h>`,
`<sys/system.h>`, and `<sys/disp.h>` normally. The overlay imports the installed
headers with `#include_next` and replaces only the affected declarations.

Assembly projects using GNU `as` can include
`<asm/wwtm_bios.inc>`. It provides English, consistently prefixed `.equ`
definitions for the BIOS vectors, service selectors, flags, screen dimensions,
and bank segments. Values disputed by the old manual follow the corroborated
AthenaBIOS/libww behavior and are annotated in the file.

Run the focused contract with:

```sh
python3 scripts/wonderwitch_sdk_contract_test.py
```

When `/opt/wonderful` is installed, the test first proves that the unmodified
headers reject or mis-type the probe, then proves that the same probe compiles
with the overlay.

`upstream/0001-fix-wwtm-bios-header-contracts.patch` applies the same four fixes
to the XML sources in the `OpenWitch/ow-libs` submodule, so the generated C
headers and non-inline library wrappers can be corrected at their source.
