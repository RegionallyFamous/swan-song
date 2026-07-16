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
repeat the top-level entity. Quartus 21.1.1 places the Assembler version in the
plain report header rather than its Summary, so that one exact header form is
also parsed and cross-checked against the toolchain and other reports. It also
requires:

- successful synthesis, flow, fit, assembly, and a final zero-error Timing
  Analyzer completion message;
- a nonempty, regular, nonsymlink RBF whose SHA-256 matches the sidecar;
- the native Analysis & Synthesis IP Cores Summary in the expected candidate
  shape, with every IP `License Type` exactly `N/A`; no evaluation/time-limit
  warnings 12188, 12189, 12190, 210039, 210042, 265069, 265072, 265073, or
  265074 and no time-limited-core info 115017 anywhere in the bounded artifact
  set; and an exact Assembler Generated Files inventory of `ap_core.sof` plus
  `ap_core.rbf`, never a `_time_limited.sof`. Intel documents both the
  [IP-summary license field](https://www.intel.com/content/www/us/en/programmable/quartushelp/current/report/rpt/rpt_file_analysis_summary.htm)
  and that [evaluation-mode IP produces only a time-limited programming file](https://www.intel.com/content/www/us/en/programmable/quartushelp/18.0/reference/glossary/def_open_core_plus.htm).
  The parser is fail-closed and synthetic-format tested, but the next retained
  genuine 21.1.1 candidate report must confirm this exact row shape before the
  new gate is treated as final-format evidence;
- logic, register, memory-bit, physical RAM-block, and PLL use (including
  capacities where Quartus reports a finite device capacity); a candidate may
  use at most 289 of the fitted device's 308 M10Ks. The clean
  resource-headroom probe confirms the compile-time-disabled Memories
  transport removes exactly 16 M10Ks, reducing the fit from 305 to 289 blocks.
  A separate source
  contract proves the capability gate itself; the lower logical memory-bit
  percentage cannot satisfy this fitted-resource gate;
- setup, hold, recovery, removal, and minimum-pulse-width summary sections at
  all four fitted operating corners with no negative slack or TNS; an explicit
  `No paths to report` is accepted only for recovery/removal. The post-fit Tcl
  gate separately checks the direct signed `get_min_pulse_width` result at
  TimeQuest's native 1 ps resolution and rejects a negative sign even when the
  displayed value is `-0.000`;
- a targeted source-synchronous SDRAM read check at every fitted corner. The
  post-fit Tcl gate must resolve exactly 16 physical `dram_dq[*]` ports and
  exactly 16 fitted capture registers, then obtain exactly one setup and one
  hold result for every bit. It records each corner's worst margin and fails on
  a missing, duplicate, nonnumeric, or negative result. The 5.9 ns input maximum
  includes the Alliance device's 5.5 ns CL3 access time plus a provisional
  0.4 ns sum of outbound-clock and inbound-data board flight; the 2.5 ns input
  minimum is the device hold specification without beneficial external flight.
  Analogue does not publish board trace delays, so these assumptions still
  require physical Pocket validation;
- `clk_74a`, `clk_74b`, and `bridge_spiclk` in the native `Clocks` panel;
- the exact six native Unconstrained Paths properties (illegal/unconstrained
  clocks, input ports/paths, and output ports/paths), with every Setup and Hold
  count equal to zero;
- exactly one native two-column `check_timing` Summary with the pinned 21.1.1
  row order (`reference_pin`, `generated_io_delay`, both partial I/O-delay
  checks, both min/max consistency checks, `partial_multicycle`, and
  `multicycle_consistency`), every issue count zero,
  plus the marker emitted only after the structured report-panel gate verifies
  those same cells. This is required because `check_timing` returns Tcl success
  even when it reports findings;
- an inventory of every `Critical Warning` in all text artifacts;
- a hard failure for Warning 332054, which proves an input/output delay
  assignment replaced another assignment instead of coexisting with it;
- a hard failure for Warning 15069, which means PLL loss-of-lock self-reset is
  missing the gated lock counter Quartus requires for correct operation;
- a complete native Connectivity Checks inventory whenever Warning 12241 is
  present. Every warning row must match the reviewed 120-row set by exact
  hierarchy, port, direction, and detail text. The policy also SHA-256-binds
  the relevant source/configuration files; a missing, changed, duplicated, or
  added row, a changed source, or a summary/detail count mismatch fails. This
  is an exact source-bound review, not a warning-ID or warning-count waiver.

Unknown, missing, duplicate, contradictory, malformed, empty, or symlinked
inputs fail. Vendor `.rpt` files are decoded as UTF-8 with one narrowly scoped
compatibility rule for Quartus 21.1.1: a standalone Latin-1 `0xB0` temperature
degree byte is normalized to `°`. No other invalid UTF-8 byte is accepted, and
the allowance does not apply to metadata, logs, provenance, or sidecars.

The reviewed connectivity manifest and exact rows live in
`toolchains/quartus-21.1.1/connectivity-warning-12241.json` and its bound TSV.
The manifest records the originating run/report/inventory hashes. Its accepted
set has no excluded defects; any removed defect reappearing fails review.

Run the focused synthetic suite with:

```sh
python3 scripts/quartus_fit_audit_test.py
python3 scripts/quartus_connectivity_policy_test.py
python3 scripts/pocket_pll_reset_contract_test.py
python3 scripts/quartus_signoff_paths_test.py
python3 scripts/pocket_sdram_constraint_test.py
python3 scripts/pocket_apf_boundary_constraint_test.py
```

On a real Docker build, the deterministic output is
`quartus-audit-candidate.json`. Its magic is
`SWAN_SONG_QUARTUS_AUDIT_V1`, not the packager's
release-required `SWAN_SONG_RELEASE_EVIDENCE_V2`. It always contains
`release_eligible: false`, `pocket_hardware: false`, `dock_hardware: false`, and
`compressed_bitstream: null`. It therefore cannot replace physical Pocket and
Dock validation or a reviewed release-evidence record. Release Evidence V2 may
bind this file, but the packager recomputes it from the complete artifact set
and separately requires the final compression and Pocket/Dock review gates;
embedding a passing candidate audit does not make the audit release-eligible.

For a candidate workflow run, GitHub also signs that exact candidate audit and
the artifact bundle preserves the resulting
`quartus-audit-candidate.attestation.json`. Stable assembly uses `gh
attestation verify` with GitHub's current official online Sigstore/TUF trust
material and restricts the certificate to repository
`RegionallyFamous/swansong-core`, workflow `.github/workflows/quartus-fit.yml`,
`main`, and the exact source commit. Its signed run-invocation URI must match
the run ID and attempt recorded inside the audited build metadata. Two release
candidates must have different signed run IDs and different fresh job nonces,
while reproducing byte-identical RBF and build ID files. This proves distinct
signed workflow executions, not distinct physical runner hosts; the same
self-hosted runner may service both executions.

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

## Current exact-source engineering evidence

A trusted DigitalOcean lab run completed a fresh synthesis, fit, assembly, and
TimeQuest analysis of temporary non-public source commit
`1e32ff6a01ea37bbe290ec7d32ec981652ad9c03` at epoch `1784047383`. The retained
`ap_core.rbf` has SHA-256
`fde228ce80fb43e6155cd64dd51022216121cd3f4ae8ac9623da78d20655a580`.
The fit reports 11,761/18,480 ALMs (64%), 13,827 registers,
2,622,848/3,153,920 memory bits (83%), 289/308 RAM blocks, 23/66 DSP blocks,
and 1/4 PLLs.

Strict post-fit signoff passed with these exact worst setup and hold slacks:

| Operating corner | Worst setup | Worst hold | Worst SDRAM DQ setup | Worst SDRAM DQ hold |
| --- | ---: | ---: | ---: | ---: |
| slow 85 C, 1100 mV | +0.477 ns | +0.340 ns | +1.115 ns | +3.139 ns |
| slow 0 C, 1100 mV | +0.220 ns | +0.331 ns | +1.208 ns | +3.056 ns |
| fast 85 C, 1100 mV | +1.745 ns | +0.080 ns | +4.308 ns | +0.592 ns |
| fast 0 C, 1100 mV | +1.757 ns | +0.010 ns | +4.521 ns | +0.409 ns |

Recovery, removal, and minimum-pulse-width results are positive at all four
corners. The eight `check_timing` checks report zero findings, unconstrained
path counts are zero, and the timing and minimum-pulse gates report no negative
paths. The report contains these four exact SDRAM markers, each proving all 16
setup and all 16 hold paths rather than only the single worst bit:

```text
SWAN_SONG_SDRAM_DQ_V1 corner slow|85|1100 setup_paths 16 setup_worst 1.115 hold_paths 16 hold_worst 3.139
SWAN_SONG_SDRAM_DQ_V1 corner slow|0|1100 setup_paths 16 setup_worst 1.208 hold_paths 16 hold_worst 3.056
SWAN_SONG_SDRAM_DQ_V1 corner fast|85|1100 setup_paths 16 setup_worst 4.308 hold_paths 16 hold_worst 0.592
SWAN_SONG_SDRAM_DQ_V1 corner fast|0|1100 setup_paths 16 setup_worst 4.521 hold_paths 16 hold_worst 0.409
```

Warning 15069 and the unnumbered `RST port on the PLL is not properly
connected` warning are absent. The surrounding build command nevertheless
returned 1 after the successful compile because the source-bound connectivity
policy still binds older source. That fail-closed policy result is the only
reason this run did not produce an accepted candidate audit; it is not a fit,
assembly, RBF-generation, or timing failure.

This evidence is not a public final-commit build, a second byte-identical RBF,
Release Evidence V2, or physical Pocket/Dock proof. Release closure still
requires a reviewed source-current connectivity manifest, a clean accepted
build of the exact final public commit, a second identical RBF/build ID, and the
separately recorded physical QA matrix.

## Basis and current limitation

Altera documents the Analysis & Synthesis Summary, Fitter Summary, and
Assembler Summary as the sources of their status and target identity fields:

- <https://www.intel.com/content/www/us/en/programmable/quartushelp/16.0/report/rpt/rpt_file_analysis_summary.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/15.1/report/rpt/rpt_file_fitter_summary.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/17.0/report/rpt/rpt_file_assembler_summary.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/current/report/rpt/rpt_file_analysis_summary.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/18.0/reference/glossary/def_open_core_plus.htm>

TimeQuest defines slack as the margin against a timing requirement and states
that unconstrained setup, hold, recovery, and removal paths cannot have slack
calculated. Its multicorner summary reports worst slack and design-wide TNS for
those analyses:

- <https://www.intel.com/content/www/us/en/programmable/quartushelp/15.1/analyze/sta/sta_about_sta.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/24.2/analyze/sta/sta_com_report_unconstrained_paths.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/23.4/report/rpt/rpt_file_multicorner_timing.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/22.4/analyze/sta/sta_com_rep_clocks.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/17.0/msgs/msgs/wsgn_connectivity_warnings.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/current/report/rpt/rpt_file_fit_feature_specific.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/18.1/msgs/msgs/ecut_pll_uses_self_reset_gate_lock_counter_not_specified.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/17.1/tafs/tafs/tcl_pkg_sta_ver_1.0_cmd_check_timing.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/20.3/tafs/tafs/tcl_pkg_sta_ver_1.0_cmd_get_min_pulse_width.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/20.3/tafs/tafs/tcl_pkg_sta_ver_1.0_cmd_report_min_pulse_width.htm>
- <https://www.intel.com/content/www/us/en/programmable/quartushelp/current/tafs/tafs/tcl_pkg_report_ver_2.1_cmd_get_number_of_rows.htm>

No genuine Swan Song Quartus 21.1.1 report set is checked into the repository.
The parser is pinned to the native shapes observed in the first complete
Swan Song Quartus Lite 21.1.1 report set, including the Assembler's plain
version header and the Fitter's Latin-1 temperature degree bytes, and covered
by narrow synthetic fixtures. Any new format difference must be reviewed
against the genuine report and added with a regression fixture. The stock
Unconstrained Paths Summary exposes Setup
and Hold property counts; if release policy later requires a separate explicit
recovery/removal unconstrained-path listing, retain and audit an additional
`report_ucp` artifact rather than inventing fields the stock report does not
contain. Do not weaken a missing/unknown-field failure merely to make a build
green.
