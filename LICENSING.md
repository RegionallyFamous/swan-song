# Swan Song licensing release gate

Swan Song is **not cleared for binary distribution yet**. The checked-in
`release-policy.json` keeps
`distribution_and_licensing_authorized` false, and the packaged
`LICENSE-MANIFEST.json` independently keeps the licensing review incomplete.
Neither flag should change until every blocker below has a cited review record.

This is an engineering provenance record, not legal advice. It distinguishes
facts visible in primary source history from decisions that require a
copyright holder or qualified reviewer.

## What is proved

- MiSTer's pinned `WonderSwan.sv` expressly offers the WonderSwan program
  under GPL-2.0-or-later and credits Robert Peip and Sorgelig. Pocket's
  `wonderswan.sv` adaptation omitted that header; the Git history still proves
  the derivation, but the notice should be restored in the final source.
- `ddram.sv` and `sdram.sv` retain GPL-3.0-or-later notices. The release
  package now carries both complete GPLv2 and GPLv3 texts.
- Four Pocket utility files retain Adam Gastineau's MIT notice. The official
  Chip32 assembler repository has Peter Lemon's MIT notice. Both complete
  notices are now packaged.
- Analogue APF and Intel/Altera-generated files retain their distinct notices.
  Those notices are now surfaced in the package without interpreting them.
- The APF header's official EULA link resolves to Analogue's August 14, 2022
  PDF (SHA-256
  `1a2a6d89bbeefc37b5ebe8839daa77ed04d7f2e5b842e0169ca5c06bb392d173`).
  Section 2 permits developers to market, sell, or distribute Developer
  Applications, while separately restricting publication, copying, and
  modification of the underlying Analogue software. Section 1 preserves the
  MIT/GPL conflict rule. The remaining APF question is therefore the public
  modified APF source and combined terms, not whether Developer Applications
  may ever be distributed.
- All 19 files under `testroms/spritepriority`, `testroms/timingtest`, and
  `testroms/windowtest` are byte-identical to MiSTer commit
  `8f7a4d670b4635eda0e518e7fd9a17ef8610db79`. Robert Peip introduced the
  timing/window assets in `30f74aa4c02856763721a2ed00c8feed55300893` and
  the sprite-priority assets in
  `921240c3c4f67f545e52efe2050a288cfc2f4f2d`. Neither the files nor those
  commit messages state a separate grant, so the manifest records
  `NOASSERTION` instead of guessing.

## Blocking decisions

1. **Project contribution declaration.** Regionally Famous must declare a
   license for its original source, tests, documentation, and generated art,
   and a reviewer must confirm the combined-work license and required notices.
2. **Inherited program notice.** Restore the pinned MiSTer
   GPL-2.0-or-later/copyright notice to the Pocket-derived top level after the
   currently active RTL integration is complete. Record maintainer
   confirmation if the release reviewer requires it.
3. **Pocket adaptation grant.** Record Adam Gastineau's intended grant for
   the unheaded Pocket-specific adaptation files. A repository-level GPLv2
   text is evidence, but the audit does not turn it into a file-level grant.
4. **APF source/combined terms.** The August 14, 2022 EULA expressly permits
   distribution of Developer Applications. Obtain or record clarification for
   public redistribution of the modified APF source itself and the final
   combined-license/notice treatment.
5. **Intel/Altera terms.** Review the accepted Quartus Prime Lite 21.1.1 and
   generated-IP terms. Confirm from the final assembler report that the RBF is
   unrestricted and contains no evaluation/time-limited IP.
6. **Legacy test assets.** Obtain a grant for the 19 exact MiSTer test assets,
   or remove/replace them and ensure the release source bundle does not contain
   them. They are never placed in the Pocket binary package.
7. **Exact source delivery.** Publish and test retrieval of the corresponding
   source for the exact release commit, with build instructions and all needed
   notices. A repository URL alone is not recorded as completion.

## Draft requests

### Robert Peip / MiSTer WonderSwan

> Swan Song derives from your MiSTer WonderSwan core. Could you confirm whether
> the files in `testroms/spritepriority`, `testroms/timingtest`, and
> `testroms/windowtest`, introduced by commits `921240c` and `30f74aa`,
> are offered under the same GPL-2.0-or-later terms stated in
> `WonderSwan.sv`? Could you also confirm that redistribution of the modified
> core source and Pocket bitstream under GPLv3-or-later, with the original
> credits and notices preserved, matches your intent?

### Adam Gastineau / agg23

> Swan Song derives from `agg23/openfpga-wonderswan` commit `073213a`.
> The Pocket top-level adaptation omitted MiSTer's GPL-2.0-or-later header,
> while several Pocket utility files have your separate MIT notice. Could you
> confirm the intended license for the Pocket-specific adaptation and whether
> redistribution of the combined modified Pocket core under GPLv3-or-later,
> preserving all MIT and upstream notices, matches your intent?

### Analogue developer support

> We are preparing a free openFPGA WonderSwan core derived from
> `open-fpga/core-template` v1.3.0. We preserve the APF Software License
> Agreement header and its MIT/GPL conflict clause. The linked August 14, 2022
> EULA permits distribution of Developer Applications but separately restricts
> publication/copying/modification of Analogue Software. Please confirm the
> notice and source requirements for publishing our modified APF template
> files alongside the compiled Pocket RBF.

### Intel FPGA support / release reviewer

> The final core is built with Quartus Prime Lite 21.1.1 for Cyclone V and uses
> generated PLL, DDIO, and memory-function files retaining Intel/Altera
> notices. Please identify the exact applicable 21.1.1 agreements and confirm
> whether an unrestricted RBF produced with no evaluation/time-limited IP may
> be redistributed for programming the Analogue Pocket's Intel FPGA, and which
> notices must accompany it.

The package-facing texts and component map live in
`dist/Cores/RegionallyFamous.SwanSong/`. `UPSTREAMS.md` contains the full
technical provenance trail.
