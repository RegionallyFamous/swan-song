# Swan Song release decisions

This is the short owner/reviewer decision record that must be completed before
Swan Song can move from a hardware-QA candidate to a public release. It is not
legal advice and does not replace the evidence gates in the repository.

## Owner decisions still required

- [ ] **Original-work license.** Regionally Famous selects terms for its
  original source, tests, documentation, and artwork. The current manifest uses
  `NOASSERTION`; do not replace it with a blanket SPDX label because inherited
  files retain GPL-2.0-only, GPL-2.0-or-later, GPL-3.0-or-later, MIT, APF, and
  Intel/Altera-specific notices. A combined-work reviewer must approve the
  final notice plan.
- [ ] **First public version.** Recommended starting point: a preview/RC such
  as `0.9.0-rc.1`, not `1.0.0`, while Memories/Sleep, the named commercial-title
  trace, and the original brief's full mapper/flash scope remain open. Choose
  `1.0.0` only if the owner explicitly decides those items are not v1 blockers.
  This is an independent `RegionallyFamous.SwanSong` release, so it does not
  have to sort after predecessor `agg23.WonderSwan` 1.0.1.
- [ ] **Release date.** Set `date_release` to the actual publication date in
  `YYYY-MM-DD` form only in the final reviewed release change.
- [ ] **Firmware floor.** Decide whether the public support floor is Analogue
  [OS 2.6.0](https://www.analogue.co/support/pocket/firmware/2.6.0), which is the
  exact version required by the 31-case hardware-QA
  protocol, or whether older firmware will receive a separately evidenced
  support tier. Do not imply that framework `2.3` alone proves the tested host
  experience.
- [ ] **Distribution authorization.** Set
  `distribution_and_licensing_authorized` only after all six manifest blocker
  IDs have a cited resolution and the exact corresponding source is publicly
  retrievable.
- [ ] **Immutable release protection.** Enable GitHub immutable releases for
  the repository before publication. Create the release as a draft, attach the
  exact seven assembler outputs, and publish only after the asset inventory is
  complete. This checklist does not authorize automation to change the
  repository setting.

## Evidence that must be newly produced

- [ ] Run the complete regression on the final commit in the pinned Linux
  toolchain. The signed Quartus pair for development commit `a897ecbf` does not
  replace an exact-final-commit regression.
- [ ] **Build the final commit.** Development commit `a897ecbf` already passes
  the strict fit/TimeQuest/IP-license audit in signed workflow runs
  `29503168418` and `29505865127`; both produce byte-identical RBF and build-ID
  files. If the exact public commit or epoch changes after source,
  documentation, policy, version, or date review, reproduce that final commit
  in two new distinct signed workflow executions.
- [ ] Test the exact final package on physical Pocket and Dock hardware. All 31
  cases and their evidence artifacts must pass, including the dedicated
  undocked PocketOS 2.6 Auto Off dirty-save flush/reload case with no manual
  power, menu, input, Dock, or USB SD intervention; no
  simulation-inferred result is accepted.
- [ ] Preserve the accepted hardware manifest and private inventory. Release
  Evidence V2 re-verifies and hash-binds both, and requires their RBF,
  version, date, persistent-setting catalogue, and all 13 installed
  Pocket-facing payloads to match the package.
- [ ] **Preserve both signed Quartus candidates.** Download and retain the two
  complete artifact bundles from two distinct `quartus-fit.yml` workflow runs
  with different fresh job nonces. Each must contain its candidate audit and
  GitHub attestation bundle for the exact final commit. A copied directory or
  rerun of the same signed execution is not a second build origin.
- [ ] **Publish the exact seven-file release.** Publish the assembler's release
  ZIP, package-provenance sidecar, corresponding-source tar, signed Quartus
  provenance tar, reviewed `release-body.md`, release manifest, and
  `SHA256SUMS` with the exact source commit. Pass the release body's reviewed
  SHA-256 back to the stable assembler before `--apply`, then verify every
  public download from a clean machine. After publishing the complete draft as
  an immutable release, require `gh release verify` and `gh release
  verify-asset` to pass before announcing it.

## Current truth

The `a897ecbf` development package has a valid byte-identical signed Quartus
candidate pair and is useful for controlled testing, but both audits correctly
record `release_eligible: false` and no public release is authorized. The six
unresolved licensing IDs and their evidence are authoritative in
`dist/Cores/RegionallyFamous.SwanSong/LICENSE-MANIFEST.json`.
