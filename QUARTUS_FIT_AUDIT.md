# Quartus fit and TimeQuest candidate audit

The Mac Docker build runs `scripts/quartus_fit_audit.py` after Quartus exits
successfully. This is a second, fail-closed gate: a process exit code alone is
not accepted as evidence that the design fitted or met timing.

The auditor requires the exact Quartus Prime Lite 21.1.1 Build 850 identity,
`ap_core` revision, `apf_top` top-level entity, Cyclone V family, and
`5CEBA4F23C8` device in every flow, fitter, assembler, and TimeQuest report. It
also requires:

- successful flow, fit, assembly, and timing-analysis status;
- a nonempty, regular, nonsymlink RBF whose SHA-256 matches the sidecar;
- logic, register, memory-bit, and PLL use (including capacities where Quartus
  reports a finite device capacity);
- setup, hold, recovery, and removal summary sections with no negative slack or
  TNS; an explicit `No paths to report` is accepted only for recovery/removal;
- `clk_74a`, `clk_74b`, and `bridge_spiclk` in Clock Summary;
- explicit zero counts for setup, hold, recovery, and removal in Unconstrained
  Paths Summary;
- an inventory of every `Critical Warning` in all text artifacts.

Unknown, missing, duplicate, contradictory, malformed, empty, or symlinked
inputs fail. Run the focused synthetic suite with:

```sh
python3 scripts/quartus_fit_audit_test.py
```

On a real Docker build, the deterministic output is
`quartus-audit-candidate.json`. Its magic is
`SWAN_SONG_QUARTUS_AUDIT_V1`, not the packager's
`SWAN_SONG_RELEASE_EVIDENCE_V1`. It always contains
`release_eligible: false`, `pocket_hardware: false`, `dock_hardware: false`, and
`compressed_bitstream: null`. It therefore cannot replace physical Pocket and
Dock validation or a reviewed release-evidence record.

The trusted VM wrapper additionally generates `container-provenance.json` and
`container-packages.tsv` in a host-only temporary directory before the fit. It
forces reviewed entrypoints for every image command, gives the fit container an
empty writable artifact mount, and merges the genuine pair only after the
container exits; any container-created reserved provenance name fails closed.
The former file binds the immutable local Docker image ID, privacy-stripped
registry manifest digests (never registry/repository coordinates), the
validated Quartus labels, and the size/count/SHA-256 of the sorted package
manifest. The bounded evidence collector revalidates that pair before upload.
These files identify the environment for one candidate; they are not a second
fit and do not prove that Quartus emits a reproducible RBF.

## Basis and current limitation

Altera documents the Fitter Summary as the source of fit status, version,
revision, top-level, family, and resource utilization, and the Assembler Summary
as the source of assembly status and target identity:

- <https://www.intel.com/content/www/us/en/programmable/quartushelp/15.1/report/rpt/rpt_file_fitter_summary.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/17.0/report/rpt/rpt_file_assembler_summary.htm>

TimeQuest defines slack as the margin against a timing requirement and states
that unconstrained setup, hold, recovery, and removal paths cannot have slack
calculated. Its multicorner summary reports worst slack and design-wide TNS for
those analyses:

- <https://www.intel.com/content/www/us/en/programmable/quartushelp/15.1/analyze/sta/sta_about_sta.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/24.2/analyze/sta/sta_com_report_unconstrained_paths.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/23.4/report/rpt/rpt_file_multicorner_timing.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/22.4/analyze/sta/sta_com_rep_clocks.htm>

No genuine Swan Song Quartus 21.1.1 report set is checked into the repository
yet. The parser consequently accepts only a deliberately narrow semicolon-table
format covered by synthetic fixtures. The first real fit may reveal harmless
format differences; those must be reviewed against the official report and
added with a regression fixture. Do not weaken a missing/unknown-field failure
merely to make a build green.
