# Upstream provenance

Pinned on 2026-07-12:

| Component | Repository | Commit | License |
| --- | --- | --- | --- |
| Pocket baseline | https://github.com/agg23/openfpga-wonderswan | `073213a2e5992cff23b174d17763cb6354ee862b` | GPL v2 top-level; file notices vary |
| WonderSwan system reference | https://github.com/MiSTer-devel/WonderSwan_MiSTer | `8f7a4d670b4635eda0e518e7fd9a17ef8610db79` | GPL v2 top-level; file notices vary |
| APF utility reference | https://github.com/agg23/analogue-pocket-utils | `78482d1b363606336f4535aa0adc2e957bc20558` | MIT |

The repository history preserves Adam Gastineau's port commits. Robert Peip is
the original WonderSwan FPGA core author. Imported files retain their own
copyright and license notices: notably, `rtl/ddram.sv` and `rtl/sdram.sv` name
Sorgelig and grant GPL v3-or-later, while each pinned repository's top-level
`LICENSE` contains the GPL v2 text. The APF utility reference has an MIT license.
The checked-in notices therefore do not support describing all RTL uniformly
as GPL-2.0. Whether otherwise unheaded project code is GPL-v2-only or permits a
later version is not stated in these files, so the mixed-version notice set
needs review before distributing a new combined build.

The checked-in `testroms/` tree is byte-identical to the pinned MiSTer
`testroms/` directory. Those individual test files do not carry separate
license headers; the source repository supplies its top-level GPL v2 license.
The directory contains no commercial game ROM.
