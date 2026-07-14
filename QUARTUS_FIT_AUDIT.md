# Quartus fit and TimeQuest candidate audit

The Mac Docker build runs `scripts/quartus_fit_audit.py` after Quartus exits
successfully. This is a second, fail-closed gate: a process exit code alone is
not accepted as evidence that the design fitted or met timing.

The auditor requires the exact Quartus Prime Lite 21.1.1 Build 850 identity,
`ap_core` revision, `apf_top` top-level entity, Cyclone V family, and
`5CEBA4F23C8` device. It reads those values from each report's native 21.1.1
shape: the Analysis & Synthesis Summary plus its three-column Settings table;
the complete Flow, Fitter, and Assembler summaries; and the Timing Analyzer
Summary, which identifies the revision, device family, and device but does not
repeat the top-level entity. It also requires:

- successful synthesis, flow, fit, assembly, and a final zero-error Timing
  Analyzer completion message;
- a nonempty, regular, nonsymlink RBF whose SHA-256 matches the sidecar;
- logic, register, memory-bit, and PLL use (including capacities where Quartus
  reports a finite device capacity);
- setup, hold, recovery, and removal summary sections with no negative slack or
  TNS; an explicit `No paths to report` is accepted only for recovery/removal;
- `clk_74a`, `clk_74b`, and `bridge_spiclk` in the native `Clocks` panel;
- the exact six native Unconstrained Paths properties (illegal/unconstrained
  clocks, input ports/paths, and output ports/paths), with every Setup and Hold
  count equal to zero;
- an inventory of every `Critical Warning` in all text artifacts;
- a review failure for Warning 12241, with the complete Analysis & Synthesis
  map report retained for exact Connectivity Checks review rather than a broad
  waiver.

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
For a candidate JSON, it also requires every audited artifact, checks every
declared size and SHA-256, recomputes the complete audit document from the
copied bytes, and requires exact document equality. This prevents a post-audit
edit from changing gates, timing, provenance, or release claims while
preserving the artifact hashes. These files identify the environment for one
candidate; they are not a second fit and do not prove that Quartus emits a
reproducible RBF.

## Basis and current limitation

Altera documents the Analysis & Synthesis Summary, Fitter Summary, and
Assembler Summary as the sources of their status and target identity fields:

- <https://www.intel.com/content/www/us/en/programmable/quartushelp/16.0/report/rpt/rpt_file_analysis_summary.htm>
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
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/17.0/msgs/msgs/wsgn_connectivity_warnings.htm>

No genuine Swan Song Quartus 21.1.1 report set is checked into the repository
yet. The parser is pinned to the native table shapes observed in genuine
Quartus Lite 21.1.1 map and Timing Analyzer reports and covered by narrow
fixtures. The next real Swan Song fit must still validate those assumptions;
any format difference must be reviewed against the genuine report and added
with a regression fixture. The stock Unconstrained Paths Summary exposes Setup
and Hold property counts; if release policy later requires a separate explicit
recovery/removal unconstrained-path listing, retain and audit an additional
`report_ucp` artifact rather than inventing fields the stock report does not
contain. Do not weaken a missing/unknown-field failure merely to make a build
green.
