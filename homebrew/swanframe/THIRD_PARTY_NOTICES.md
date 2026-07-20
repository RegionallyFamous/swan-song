# Third-party notices

SWANFRAME is built with Wonderful Toolchain. The public release does not include
the compiler or toolchain installation, but the ROM statically links the
following runtime components.

## Wonderful target-wswan-syslibs

Installed package: `target-wswan-syslibs 0.2.0.r254.d7d97ce-1`

License: zlib

Copyright (c) 2022, 2023, 2024 Adrian "asie" Siekierka

This software is provided 'as-is', without any express or implied warranty. In
no event will the authors be held liable for any damages arising from the use
of this software.

Permission is granted to anyone to use this software for any purpose, including
commercial applications, and to alter it and redistribute it freely, subject
to the following restrictions:

1. The origin of this software must not be misrepresented; you must not claim
   that you wrote the original software. If you use this software in a product,
   an acknowledgment in the product documentation would be appreciated but is
   not required.
2. Altered source versions must be plainly marked as such, and must not be
   misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.

## Wonderful IA-16 GCC runtime

Installed package: `toolchain-gcc-ia16-elf-gcc-libs
6.3.0.r147159.e7507d1845e-1`

License: `GPL-3.0-or-later WITH GCC-exception-3.1`

The GCC Runtime Library Exception permits eligible compiled programs to use
the GCC runtime without imposing GCC's license on independently written code.
The SWANFRAME source is independently released under GPL-3.0-or-later. The
exception text and GCC sources are available from the Wonderful Toolchain GCC
package source identified above.

## Build-time asset tools

Wonderful's `wf-process` Lua modules used by this project identify themselves
as MIT-licensed. They run at build time and are not embedded as Lua source in
the distributed ROM.
