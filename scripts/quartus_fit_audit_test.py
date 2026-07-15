#!/usr/bin/env python3

import csv
import json
from pathlib import Path
import tempfile
import unittest

import quartus_fit_audit as audit
import quartus_container_provenance as container_provenance
from quartus_report_text import decode_quartus_report


VERSION = "Version 21.1.1 Build 850 06/23/2022 SJ Lite Edition"
IMAGE_ID = "sha256:" + "a" * 64
SOURCE_ROOT = Path(__file__).resolve().parents[1]

# These fixtures use the table shapes emitted by genuine Quartus 21.1.1
# map.rpt and sta.rpt files: map Device is a 3-column Settings value, while
# Timing Analyzer identity, Clocks, Unconstrained Paths, and completion are
# represented in their separate native sections.


def report(summary: str, status_key: str, status: str = "Successful - fixture") -> str:
    return f"""+ fixture +
; {summary} ;
+ fixture +
; {status_key} ; {status} ;
; Quartus Prime Version ; {VERSION} ;
; Revision Name ; ap_core ;
; Top-level Entity Name ; apf_top ;
; Family ; Cyclone V ;
; Device ; 5CEBA4F23C8 ;
"""


def assembler_generated_files_report() -> str:
    return """+ fixture +
; Assembler Generated Files ;
+ fixture +
; File Name ;
+ fixture +
; /fixture/output_files/ap_core.sof ;
; /fixture/output_files/ap_core.rbf ;
+ fixture +
"""


def assembler_report(
    header_version: str = VERSION.removeprefix("Version "),
    *,
    include_table_version: bool = False,
) -> str:
    body = report("Assembler Summary", "Assembler Status")
    if not include_table_version:
        body = body.replace(f"; Quartus Prime Version ; {VERSION} ;\n", "")
    header = f"Quartus Prime Version {header_version}\n" if header_version else ""
    return f"""Assembler report for ap_core
{header}
{body}
{assembler_generated_files_report()}
"""


def map_report(
    status: str = "Successful - fixture", device: str = "5CEBA4F23C8"
) -> str:
    version = VERSION.removeprefix("Version ")
    return f"""Analysis & Synthesis report for ap_core
Quartus Prime Version {version}

+--------------------------------------------------------------+
; Analysis & Synthesis Summary                                 ;
+-------------------------------------+------------------------+
; Analysis & Synthesis Status         ; {status} ;
; Quartus Prime Version               ; {version} ;
; Revision Name                       ; ap_core ;
; Top-level Entity Name               ; apf_top ;
; Family                              ; Cyclone V ;
+-------------------------------------+------------------------+

+--------------------------------------------------------------+
; Analysis & Synthesis Settings                                ;
+-----------------------+----------------+---------------------+
; Option                ; Setting        ; Default Value       ;
+-----------------------+----------------+---------------------+
; Device                ; {device} ;                     ;
; Top-level entity name ; apf_top        ; apf_top             ;
; Family name           ; Cyclone V      ; Cyclone V           ;
; Intel FPGA IP Evaluation Mode ; Enable ; Enable ;
+-----------------------+----------------+---------------------+

+ fixture +
; Analysis & Synthesis IP Cores Summary ;
+ fixture +
; Vendor ; IP Core Name ; Version ; Release Date ; License Type ; Entity Instance ; IP Include File ;
+ fixture +
; Altera ; RAM: 2-PORT ; 18.1 ; N/A ; N/A ; |apf_top|mf_datatable:idt ; apf/mf_datatable.v ;
; Altera ; altera_pll ; 21.1 ; N/A ; N/A ; |apf_top|mf_pllbase:mp1 ; core/mf_pllbase.v ;
; Altera ; ALTDDIO_BIDIR ; 18.1 ; N/A ; N/A ; |apf_top|mf_ddio_bidir_12:iscc ; apf/mf_ddio_bidir_12.v ;
; Altera ; ALTDDIO_BIDIR ; 18.1 ; N/A ; N/A ; |apf_top|mf_ddio_bidir_12:isclk ; apf/mf_ddio_bidir_12.v ;
; Altera ; ALTDDIO_BIDIR ; 18.1 ; N/A ; N/A ; |apf_top|mf_ddio_bidir_12:isco ; apf/mf_ddio_bidir_12.v ;
+ fixture +
"""


def reviewed_connectivity_report() -> str:
    policy = json.loads(
        (
            SOURCE_ROOT
            / "toolchains/quartus-21.1.1/connectivity-warning-12241.json"
        ).read_text(encoding="utf-8")
    )
    with (SOURCE_ROOT / policy["allowlist"]["path"]).open(
        encoding="utf-8"
    ) as source:
        items = list(csv.DictReader(source, delimiter="\t"))
    groups = {}
    for item in items:
        groups.setdefault(item["hierarchy"], []).append(item)
    lines = [
        f"Warning (12241): {len(groups)} hierarchies have connectivity warnings - "
        "see the Connectivity Checks report folder"
    ]
    for hierarchy, rows in groups.items():
        lines.extend(
            (
                f'; Port Connectivity Checks: "{hierarchy}" ;',
                "+ fixture +",
                "; Port ; Type ; Severity ; Details ;",
                "+ fixture +",
            )
        )
        lines.extend(
            f'; {item["port"]} ; {item["type"]} ; Warning ; '
            f'{item["details"]} ;'
            for item in rows
        )
        lines.append("+ fixture +")
    return "\n".join(lines) + "\n"


def sta_report(slacks=None, clocks=None, unconstrained=None, no_path_analyses=()) -> str:
    slacks = slacks or {name: "0.100" for name in audit.ANALYSES}
    clocks = clocks or list(audit.REQUIRED_CLOCKS) + ["pll_core"]
    unconstrained = unconstrained or {
        name: {"setup": 0, "hold": 0}
        for name in audit.UNCONSTRAINED_PROPERTIES
    }
    text = f"""Timing Analyzer report for ap_core
Quartus Prime Version 21.1.1 Build 850 06/23/2022 SJ Lite Edition

+----------------------------------------------------------------------------+
; Timing Analyzer Summary                                                    ;
+-----------------------+----------------------------------------------------+
; Quartus Prime Version ; {VERSION} ;
; Timing Analyzer       ; Legacy Timing Analyzer ;
; Revision Name         ; ap_core ;
; Device Family         ; Cyclone V ;
; Device Name           ; 5CEBA4F23C8 ;
; Timing Models         ; Final ;
; Delay Model           ; Combined ;
; Rise/Fall Delays      ; Enabled ;
+-----------------------+----------------------------------------------------+

+--------------------------------------------------------------------------+
; Clocks                                                                   ;
+---------------+------+--------+-----------+-------+-------+------------+-----------+-------------+-------+--------+-----------+------------+----------+--------+--------+-----------+
; Clock Name    ; Type ; Period ; Frequency ; Rise  ; Fall  ; Duty Cycle ; Divide by ; Multiply by ; Phase ; Offset ; Edge List ; Edge Shift ; Inverted ; Master ; Source ; Targets   ;
+---------------+------+--------+-----------+-------+-------+------------+-----------+-------------+-------+--------+-----------+------------+----------+--------+--------+-----------+
"""
    for clock in clocks:
        text += (
            f"; {clock} ; Base ; 13.468 ; 74.25 MHz ; 0.000 ; 6.734 ; "
            f"; ; ; ; ; ; ; ; ; ; {{ {clock} }} ;\n"
        )
    text += "+---------------+------+--------+-----------+-------+-------+------------+-----------+-------------+-------+--------+-----------+------------+----------+--------+--------+-----------+\n"
    for corner in audit.EXPECTED_TIMING_CORNERS:
        for analysis in audit.ANALYSES:
            title = analysis.replace("_", " ").title()
            text += f"; {corner} {title} Summary ;\n"
            if analysis in no_path_analyses:
                text += "No paths to report.\n"
                continue
            text += f"""; Clock ; Slack ; End Point TNS ;
; clk_74a ; {slacks[analysis]} ; 0.000 ;
"""
    for _ in range(2):
        text += "; Unconstrained Paths Summary ;\n; Property ; Setup ; Hold ;\n"
        for property_name in audit.UNCONSTRAINED_PROPERTIES:
            display = property_name.title()
            text += (
                f"; {display} ; {unconstrained[property_name]['setup']} ; "
                f"{unconstrained[property_name]['hold']} ;\n"
            )
    text += """+ fixture +
; Summary ;
+ fixture +
; Check ; Number of Issues Found ;
+ fixture +
; reference_pin ; 0 ;
; generated_io_delay ; 0 ;
; partial_input_delay ; 0 ;
; partial_output_delay ; 0 ;
; io_min_max_delay_consistency ; 0 ;
; partial_min_max_delay ; 0 ;
; partial_multicycle ; 0 ;
; multicycle_consistency ; 0 ;
+ fixture +
SWAN_SONG_CHECK_TIMING_V2 checks 8 findings 0
SWAN_SONG_TIMING_GATE_V1 corners 4 analyses 4 negative_paths 0
SWAN_SONG_MIN_PULSE_GATE_V1 corners 4 worst_checks 4 negative_checks 0
"""
    for corner in ("slow|85|1100", "slow|0|1100", "fast|85|1100", "fast|0|1100"):
        text += (
            f"SWAN_SONG_SDRAM_DQ_V1 corner {corner} setup_paths 16 "
            "setup_worst 0.843 hold_paths 16 hold_worst 0.521\n"
        )
    text += (
        "; Timing Analyzer Messages ;\n"
        "Info: Quartus Prime Timing Analyzer was successful. 0 errors, 0 warnings\n"
    )
    return text


class Fixture:
    def __init__(
        self,
        root: Path,
        *,
        workflow_run_id: str = "100",
        workflow_run_attempt: str = "1",
        workflow_job_nonce: str = "0" * 32,
    ):
        self.root = root
        (root / "output_files").mkdir()
        self.write("output_files/ap_core.rbf", b"fixture-rbf\x01")
        self.write(
            "output_files/ap_core.map.rpt",
            map_report().encode(),
        )
        self.write(
            "output_files/ap_core.flow.rpt",
            report("Flow Summary", "Flow Status").encode(),
        )
        fit = report("Fitter Summary", "Fitter Status") + """; Logic utilization (in ALMs) ; 12,345 / 49,000 (25%) ;
; Total registers ; 10,001 ;
; Total block memory bits ; 300,000 / 3,383,040 (9%) ;
; Total RAM Blocks ; 280 / 308 (91%) ;
; Total PLLs ; 4 / 6 (67%) ;
"""
        self.write("output_files/ap_core.fit.rpt", fit.encode())
        self.write(
            "output_files/ap_core.asm.rpt",
            assembler_report().encode(),
        )
        self.write("output_files/ap_core.sta.rpt", sta_report().encode())
        self.write("toolchain-version.txt", f"Quartus Prime Shell\n{VERSION}\n".encode())
        self.write(
            "build-metadata.txt",
            (
                "source_commit=" + "a" * 40 + "\n"
                "source_date_epoch=1700000000\n"
                "workflow_repository=RegionallyFamous/swansong-core\n"
                "workflow_path=.github/workflows/quartus-fit.yml\n"
                "workflow_sha=" + "a" * 40 + "\n"
                f"workflow_run_id={workflow_run_id}\n"
                f"workflow_run_attempt={workflow_run_attempt}\n"
                "workflow_job=fit\n"
                f"workflow_job_nonce={workflow_job_nonce}\n"
                "platform=linux/amd64\n"
                "quartus=21.1.1.850 Lite\n"
                "device=5CEBA4F23C8\n"
            ).encode(),
        )
        self.write("build_id.mif", b"WIDTH=32; DEPTH=8; CONTENT BEGIN END;\n")
        self.write("quartus.log", b"Info: Full Compilation was successful\n")
        self.write(
            "quartus-audit-candidate.attestation.json",
            b'{"synthetic":"attestation-bundle"}\n',
        )
        packages = root / "container-packages.tsv"
        self.write("container-packages.tsv", b"bash\t5.0-6ubuntu1.2\tamd64\n")
        container_provenance.create_provenance(
            image_id=IMAGE_ID,
            repo_digests_text="",
            packages=packages,
            output=root / "container-provenance.json",
        )
        rbf_hash = audit.digest(root / "output_files/ap_core.rbf")["sha256"]
        self.write(
            "ap_core.rbf.sha256",
            f"{rbf_hash}  /artifacts/output_files/ap_core.rbf\n".encode(),
        )

    def write(self, relative: str, data: bytes) -> None:
        (self.root / relative).write_bytes(data)


class QuartusFitAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = Fixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_valid_fixture_is_deterministic_non_release_candidate(self) -> None:
        output = self.root / "candidate.json"
        self.assertEqual(audit.main(["--artifacts", str(self.root), "--output", str(output)]), 0)
        first = output.read_bytes()
        self.assertEqual(audit.main(["--artifacts", str(self.root), "--output", str(output)]), 0)
        self.assertEqual(first, output.read_bytes())
        payload = json.loads(first)["quartus_audit"]
        self.assertEqual(payload["magic"], audit.MAGIC)
        self.assertTrue(payload["audit_pass"])
        self.assertFalse(payload["release_eligible"])
        self.assertFalse(payload["candidate_gates"]["pocket_hardware"])
        self.assertFalse(payload["candidate_gates"]["dock_hardware"])
        self.assertIsNone(payload["candidate_gates"]["compressed_bitstream"])
        self.assertEqual(payload["resources"]["plls"], {"available": 6, "used": 4})
        self.assertEqual(
            payload["resources"]["ram_blocks"],
            {"available": 308, "used": 280},
        )
        self.assertTrue(payload["candidate_gates"]["ram_block_headroom"])
        self.assertTrue(
            payload["candidate_gates"]["no_evaluation_or_time_limited_ip"]
        )
        self.assertEqual(
            payload["ip_licensing"]["assembler_generated_files"],
            ["ap_core.sof", "ap_core.rbf"],
        )
        self.assertEqual(
            payload["ip_licensing"]["evaluation_mode_setting"], "Enable"
        )
        self.assertEqual(payload["ip_licensing"]["non_n_a_license_count"], 0)
        self.assertEqual(payload["ip_licensing"]["evaluation_warning_count"], 0)
        self.assertEqual(payload["ip_licensing"]["time_limited_info_count"], 0)
        self.assertEqual(
            payload["timing"]["clocks"]["required"], list(audit.REQUIRED_CLOCKS)
        )
        self.assertEqual(
            set(payload["timing"]["unconstrained_paths"]),
            set(audit.UNCONSTRAINED_PROPERTIES),
        )
        self.assertEqual(
            payload["timing"]["check_timing"]["checks"],
            list(audit.CHECK_TIMING_ROWS),
        )
        self.assertEqual(payload["timing"]["check_timing"]["findings"], 0)
        self.assertTrue(
            payload["flow"]["timing_analysis"]["status"].startswith(
                "Info: Quartus Prime Timing Analyzer was successful."
            )
        )
        self.assertEqual(payload["container_provenance"]["image_id"], IMAGE_ID)
        self.assertIn("output_files/ap_core.map.rpt", payload["artifacts"])
        self.assertEqual(
            payload["artifacts"]["output_files/ap_core.map.rpt"],
            audit.digest(self.root / "output_files/ap_core.map.rpt"),
        )
        self.assertIn("synthesis", payload["flow"])
        self.assertEqual(payload["flow"]["assembly"]["version"], VERSION)
        self.assertEqual(set(payload["artifacts"]), set(audit.REQUIRED_ARTIFACTS))
        self.assertIn("container-provenance.json", payload["artifacts"])
        self.assertIn("container-packages.tsv", payload["artifacts"])
        self.assertNotIn("release_evidence", json.loads(first))

    def test_ip_license_inventory_fails_closed(self) -> None:
        map_path = self.root / "output_files/ap_core.map.rpt"
        original = map_path.read_bytes()

        map_path.write_bytes(
            original.replace(
                b"; Altera ; RAM: 2-PORT ; 18.1 ; N/A ; N/A ;",
                b"; Altera ; RAM: 2-PORT ; 18.1 ; N/A ; Unlicensed ;",
                1,
            )
        )
        payload = audit.audit(self.root)["quartus_audit"]
        self.assertFalse(
            payload["candidate_gates"]["no_evaluation_or_time_limited_ip"]
        )
        self.assertFalse(payload["audit_pass"])
        self.assertEqual(payload["ip_licensing"]["non_n_a_license_count"], 1)
        self.assertEqual(
            payload["ip_licensing"]["non_n_a_license_entries"][0]["license_type"],
            "Unlicensed",
        )

        map_path.write_bytes(original.replace(b"Intel FPGA IP Evaluation Mode", b"Unknown Mode", 1))
        with self.assertRaisesRegex(
            audit.AuditError, "Intel FPGA IP Evaluation Mode"
        ):
            audit.audit(self.root)
        map_path.write_bytes(original)

    def test_duplicate_identical_evaluation_setting_is_rejected(self) -> None:
        map_path = self.root / "output_files/ap_core.map.rpt"
        setting = b"; Intel FPGA IP Evaluation Mode ; Enable ; Enable ;\n"
        map_path.write_bytes(map_path.read_bytes().replace(setting, setting * 2, 1))
        with self.assertRaisesRegex(
            audit.AuditError, "Intel FPGA IP Evaluation Mode"
        ):
            audit.audit(self.root)

    def test_opencore_warning_fails_candidate_gate(self) -> None:
        log_path = self.root / "quartus.log"
        log_path.write_text(
            "Warning (12188): OpenCore Plus Hardware Evaluation feature is turned on\n"
        )
        payload = audit.audit(self.root)["quartus_audit"]
        self.assertFalse(
            payload["candidate_gates"]["no_evaluation_or_time_limited_ip"]
        )
        self.assertFalse(payload["audit_pass"])
        self.assertEqual(payload["ip_licensing"]["evaluation_warning_count"], 1)
        self.assertEqual(
            payload["ip_licensing"]["evaluation_warning_entries"][0]["artifact"],
            "quartus.log",
        )

    def test_time_limited_rbf_conversion_warning_fails_candidate_gate(self) -> None:
        log_path = self.root / "quartus.log"
        log_path.write_text(
            "Warning (210042): Can't convert time-limited SOF into POF, HEX File, "
            "TTF, or RBF\n"
        )
        payload = audit.audit(self.root)["quartus_audit"]
        self.assertFalse(
            payload["candidate_gates"]["no_evaluation_or_time_limited_ip"]
        )
        self.assertFalse(payload["audit_pass"])
        self.assertEqual(payload["ip_licensing"]["evaluation_warning_count"], 1)
        self.assertEqual(
            payload["ip_licensing"]["evaluation_warning_entries"][0]["message"],
            "Warning (210042): Can't convert time-limited SOF into POF, HEX File, "
            "TTF, or RBF",
        )

    def test_time_limited_core_info_fails_candidate_gate(self) -> None:
        log_path = self.root / "quartus.log"
        log_path.write_text(
            "Info (115017): Design contains a time-limited core -- only a single, "
            "time-limited programming file can be generated\n"
        )
        payload = audit.audit(self.root)["quartus_audit"]
        self.assertFalse(
            payload["candidate_gates"]["no_evaluation_or_time_limited_ip"]
        )
        self.assertFalse(payload["audit_pass"])
        self.assertEqual(payload["ip_licensing"]["time_limited_info_count"], 1)
        self.assertEqual(
            payload["ip_licensing"]["time_limited_info_entries"][0]["message"],
            "Info (115017): Design contains a time-limited core -- only a single, "
            "time-limited programming file can be generated",
        )

    def test_time_limited_assembler_output_is_rejected(self) -> None:
        assembly_path = self.root / "output_files/ap_core.asm.rpt"
        assembly_path.write_bytes(
            assembly_path.read_bytes().replace(
                b"/fixture/output_files/ap_core.sof",
                b"/fixture/output_files/ap_core_time_limited.sof",
                1,
            )
        )
        with self.assertRaisesRegex(
            audit.AuditError,
            "assembler generated files must be exactly ap_core.sof and ap_core.rbf",
        ):
            audit.audit(self.root)

    def test_extra_relative_time_limited_assembler_output_is_rejected(self) -> None:
        assembly_path = self.root / "output_files/ap_core.asm.rpt"
        expected = b"; /fixture/output_files/ap_core.rbf ;\n"
        extra = expected + b"; ap_core_time_limited.sof ;\n"
        assembly_path.write_bytes(
            assembly_path.read_bytes().replace(expected, extra, 1)
        )
        with self.assertRaisesRegex(
            audit.AuditError,
            "assembler generated files must be exactly ap_core.sof and ap_core.rbf",
        ):
            audit.audit(self.root)

    def test_physical_ram_block_candidate_budget_is_fail_closed(self) -> None:
        fit_path = self.root / "output_files/ap_core.fit.rpt"
        original = fit_path.read_bytes()

        for used, expected in ((289, True), (290, False)):
            with self.subTest(used=used):
                fit_path.write_bytes(
                    original.replace(
                        b"280 / 308 (91%)",
                        f"{used} / 308 (94%)".encode(),
                        1,
                    )
                )
                payload = audit.audit(self.root)["quartus_audit"]
                self.assertIs(
                    payload["candidate_gates"]["ram_block_headroom"],
                    expected,
                )
                self.assertIs(payload["audit_pass"], expected)

        fit_path.write_bytes(original)

    def test_physical_ram_block_resource_shape_is_exact(self) -> None:
        fit_path = self.root / "output_files/ap_core.fit.rpt"
        original = fit_path.read_bytes()
        cases = (
            (
                original.replace(b"Total RAM Blocks", b"Unknown RAM Blocks", 1),
                "fit ram_blocks",
            ),
            (
                original.replace(b"280 / 308 (91%)", b"280", 1),
                "capacity is missing",
            ),
            (
                original.replace(b"280 / 308 (91%)", b"309 / 308 (101%)", 1),
                "invalid ram_blocks resource utilization",
            ),
            (
                original
                + b"; Total RAM Blocks ; 281 / 308 (91%) ;\n",
                "expected one unambiguous value",
            ),
        )
        for report, message in cases:
            with self.subTest(message=message):
                fit_path.write_bytes(report)
                with self.assertRaisesRegex(audit.AuditError, message):
                    audit.audit(self.root)
        fit_path.write_bytes(original)

    def test_quartus_report_decoder_normalizes_only_standalone_degree_bytes(
        self,
    ) -> None:
        self.assertEqual(
            decode_quartus_report(b"valid UTF-8: 0 \xc2\xb0C; legacy: 85 \xb0C"),
            "valid UTF-8: 0 °C; legacy: 85 °C",
        )
        self.assertEqual(
            decode_quartus_report(b"two legacy values: 0 \xb0C, 85 \xb0C"),
            "two legacy values: 0 °C, 85 °C",
        )

        # Every possible invalid single-byte UTF-8 mutation except the one
        # genuine Quartus legacy degree byte remains forbidden.
        for value in range(0x80, 0x100):
            if value == 0xB0:
                continue
            with self.subTest(invalid_byte=f"0x{value:02x}"):
                with self.assertRaises(UnicodeDecodeError):
                    decode_quartus_report(bytes((value,)))

        for mutation in (b"\xb0\xff", b"\xff\xb0", b"\xb0\xe2\xb0x"):
            with self.subTest(mixed_invalid_bytes=mutation.hex()):
                with self.assertRaises(UnicodeDecodeError):
                    decode_quartus_report(mutation)

    def test_latin1_degree_allowance_is_limited_to_vendor_reports(self) -> None:
        for relative, _ in audit.REPORTS.values():
            with self.subTest(accepted_report=relative):
                original = (self.root / relative).read_bytes()
                self.fixture.write(relative, original + b"Temperature: 85 \xb0C\n")
                audit.audit(self.root)
                self.fixture.write(relative, original)

        log = (self.root / "quartus.log").read_bytes()
        self.fixture.write("quartus.log", log + b"Temperature: 85 \xb0C\n")
        with self.assertRaisesRegex(audit.AuditError, "non-UTF-8.*quartus.log"):
            audit.audit(self.root)

        self.fixture.write("quartus.log", log)
        fit = (self.root / "output_files/ap_core.fit.rpt").read_bytes()
        self.fixture.write("output_files/ap_core.fit.rpt", fit + b"\xff\n")
        with self.assertRaisesRegex(audit.AuditError, "non-UTF-8.*ap_core.fit.rpt"):
            audit.audit(self.root)

    def test_native_assembler_header_version_is_exact_and_unambiguous(self) -> None:
        assembly_path = "output_files/ap_core.asm.rpt"

        # The preexisting table form and a matching header-plus-table form
        # remain accepted, but the genuine plain header needs no invented row.
        for contents in (
            report("Assembler Summary", "Assembler Status")
            + assembler_generated_files_report(),
            assembler_report(include_table_version=True),
        ):
            with self.subTest(accepted_form=contents.splitlines()[0]):
                self.fixture.write(assembly_path, contents.encode())
                self.assertEqual(
                    audit.audit(self.root)["quartus_audit"]["flow"]["assembly"][
                        "version"
                    ],
                    VERSION,
                )

        rejected = (
            (assembler_report(header_version=""), "unambiguous"),
            (
                assembler_report(
                    header_version="21.1.1 Build 851 06/23/2022 SJ Lite Edition"
                ),
                "21.1.1 Build 850",
            ),
            (
                assembler_report()
                + "Quartus Prime Version 21.1.1 Build 850 06/24/2022 SJ Lite Edition\n",
                "unambiguous",
            ),
            (
                assembler_report(header_version="").replace(
                    "Assembler report for ap_core",
                    f"Assembler report for ap_core {VERSION}",
                ),
                "unambiguous",
            ),
        )
        for contents, message in rejected:
            with self.subTest(rejected=message, contents=contents.splitlines()[:2]):
                self.fixture.write(assembly_path, contents.encode())
                with self.assertRaisesRegex(audit.AuditError, message):
                    audit.audit(self.root)

    def test_container_provenance_is_required_and_bound(self) -> None:
        provenance = self.root / "container-provenance.json"
        provenance.unlink()
        with self.assertRaisesRegex(audit.AuditError, "missing regular artifact"):
            audit.audit(self.root)

        container_provenance.create_provenance(
            image_id="sha256:" + "b" * 64,
            repo_digests_text="",
            packages=self.root / "container-packages.tsv",
            output=provenance,
        )
        payload = audit.audit(self.root)["quartus_audit"]
        self.assertEqual(payload["container_provenance"]["image_id"], "sha256:" + "b" * 64)
        self.assertEqual(
            payload["artifacts"]["container-provenance.json"], audit.digest(provenance)
        )

    def test_each_negative_timing_analysis_fails_closed(self) -> None:
        for analysis in audit.ANALYSES:
            with self.subTest(analysis=analysis):
                values = {name: "0.100" for name in audit.ANALYSES}
                values[analysis] = "-0.001"
                self.fixture.write("output_files/ap_core.sta.rpt", sta_report(slacks=values).encode())
                with self.assertRaisesRegex(audit.AuditError, f"negative {analysis}"):
                    audit.audit(self.root)

    def test_negative_tns_fails_closed(self) -> None:
        text = sta_report().replace("; clk_74a ; 0.100 ; 0.000 ;", "; clk_74a ; 0.100 ; -0.001 ;", 1)
        self.fixture.write("output_files/ap_core.sta.rpt", text.encode())
        with self.assertRaisesRegex(audit.AuditError, "negative setup"):
            audit.audit(self.root)

    def test_negative_zero_slack_and_tns_fail_closed(self) -> None:
        original = sta_report()
        mutations = (
            original.replace(
                "; clk_74a ; 0.100 ; 0.000 ;",
                "; clk_74a ; -0.000 ; 0.000 ;",
                1,
            ),
            original.replace(
                "; clk_74a ; 0.100 ; 0.000 ;",
                "; clk_74a ; 0.100 ; -0.000 ;",
                1,
            ),
        )
        for text in mutations:
            with self.subTest(text=text.splitlines()[20:24]):
                self.fixture.write("output_files/ap_core.sta.rpt", text.encode())
                with self.assertRaisesRegex(audit.AuditError, "negative setup"):
                    audit.audit(self.root)

    def test_timing_summary_requires_exactly_one_tns_column(self) -> None:
        text = sta_report().replace(
            "; Clock ; Slack ; End Point TNS ;\n; clk_74a ; 0.100 ; 0.000 ;",
            "; Clock ; Slack ;\n; clk_74a ; 0.100 ;",
            1,
        )
        self.fixture.write("output_files/ap_core.sta.rpt", text.encode())
        with self.assertRaisesRegex(audit.AuditError, "unknown setup TNS table format"):
            audit.audit(self.root)

    def test_native_check_timing_summary_fails_closed_independently(self) -> None:
        original = sta_report()
        mutations = (
            (
                original.replace("; reference_pin ; 0 ;", "; reference_pin ; 1 ;", 1),
                "nonzero",
            ),
            (
                original.replace("; generated_io_delay ; 0 ;\n", "", 1),
                "missing",
            ),
            (
                original.replace(
                    "; generated_io_delay ; 0 ;\n; partial_input_delay ; 0 ;",
                    "; partial_input_delay ; 0 ;\n; generated_io_delay ; 0 ;",
                    1,
                ),
                "reordered",
            ),
            (
                original.replace(
                    "; Check ; Number of Issues Found ;",
                    "; Check ; Issues ;",
                    1,
                ),
                "2-column table",
            ),
            (
                original.replace(audit.CHECK_TIMING_MARKER + "\n", "", 1),
                "marker",
            ),
            (
                original + audit.CHECK_TIMING_MARKER + "\n",
                "marker",
            ),
            (
                original.replace(
                    audit.CHECK_TIMING_MARKER,
                    "; Check ; Number of Issues Found ;\n"
                    + audit.CHECK_TIMING_MARKER,
                    1,
                ),
                "exactly one native",
            ),
        )
        for text, message in mutations:
            with self.subTest(message=message):
                self.fixture.write("output_files/ap_core.sta.rpt", text.encode())
                with self.assertRaisesRegex(audit.AuditError, message):
                    audit.audit(self.root)

    def test_four_corner_timing_gate_marker_is_required(self) -> None:
        text = sta_report().replace(audit.TIMING_GATE_MARKER + "\n", "", 1)
        self.fixture.write("output_files/ap_core.sta.rpt", text.encode())
        with self.assertRaisesRegex(
            audit.AuditError, "timing-gate zero-findings marker is missing"
        ):
            audit.audit(self.root)

    def test_minimum_pulse_width_gate_marker_is_exactly_once(self) -> None:
        original = sta_report()
        for text in (
            original.replace(audit.MIN_PULSE_GATE_MARKER + "\n", "", 1),
            original + audit.MIN_PULSE_GATE_MARKER + "\n",
        ):
            with self.subTest(duplicate=text.endswith(audit.MIN_PULSE_GATE_MARKER + "\n")):
                self.fixture.write("output_files/ap_core.sta.rpt", text.encode())
                with self.assertRaisesRegex(
                    audit.AuditError,
                    "minimum-pulse-width zero-findings marker is missing",
                ):
                    audit.audit(self.root)

    def test_sdram_dq_corner_markers_fail_closed(self) -> None:
        original = sta_report()
        slow85 = (
            "SWAN_SONG_SDRAM_DQ_V1 corner slow|85|1100 setup_paths 16 "
            "setup_worst 0.843 hold_paths 16 hold_worst 0.521\n"
        )
        mutations = (
            (original.replace(slow85, "", 1), "missing or unexpected"),
            (original + slow85, "duplicate SDRAM DQ timing marker"),
            (
                original.replace("setup_worst 0.843", "setup_worst -0.000", 1),
                "negative SDRAM DQ setup slack",
            ),
            (
                original.replace("hold_paths 16", "hold_paths 15", 1),
                "missing or unexpected",
            ),
        )
        for text, message in mutations:
            with self.subTest(message=message):
                self.fixture.write("output_files/ap_core.sta.rpt", text.encode())
                with self.assertRaisesRegex(audit.AuditError, message):
                    audit.audit(self.root)

    def test_replaced_io_delay_warning_332054_is_an_unwaivable_gate(self) -> None:
        self.fixture.write(
            "quartus.log",
            b"Warning (332054): Assignment set_input_delay replaced one or more "
            b'delays on port "dram_dq[0]".\n',
        )
        output = self.root / "candidate.json"
        self.assertEqual(
            audit.main(
                ["--artifacts", str(self.root), "--output", str(output)]
            ),
            1,
        )
        payload = json.loads(output.read_text())["quartus_audit"]
        self.assertFalse(payload["audit_pass"])
        self.assertFalse(
            payload["candidate_gates"]["io_delay_constraints_preserved"]
        )
        warnings = payload["constraint_replacement_warnings"]
        self.assertEqual(warnings["warning_id"], 332054)
        self.assertEqual(warnings["count"], 1)
        self.assertIn("dram_dq[0]", warnings["entries"][0]["message"])

    def test_plain_text_no_paths_is_accepted_only_for_recovery_and_removal(self) -> None:
        for analysis in ("recovery", "removal"):
            with self.subTest(accepted=analysis):
                self.fixture.write(
                    "output_files/ap_core.sta.rpt",
                    sta_report(no_path_analyses=(analysis,)).encode(),
                )
                timing = audit.audit(self.root)["quartus_audit"]["timing"]
                entry = timing["analyses"][analysis][0]
                self.assertEqual(entry["path_count"], 0)
                self.assertIsNone(entry["worst_slack"])

        for analysis in ("setup", "hold", "minimum_pulse_width"):
            with self.subTest(rejected=analysis):
                self.fixture.write(
                    "output_files/ap_core.sta.rpt",
                    sta_report(no_path_analyses=(analysis,)).encode(),
                )
                with self.assertRaisesRegex(
                    audit.AuditError, f"invalid no-paths {analysis}"
                ):
                    audit.audit(self.root)

    def test_missing_clock_and_unconstrained_path_fail_closed(self) -> None:
        self.fixture.write(
            "output_files/ap_core.sta.rpt",
            sta_report(clocks=["clk_74a", "clk_74b"]).encode(),
        )
        with self.assertRaisesRegex(audit.AuditError, "bridge_spiclk"):
            audit.audit(self.root)
        counts = {
            name: {"setup": 0, "hold": 0}
            for name in audit.UNCONSTRAINED_PROPERTIES
        }
        counts["unconstrained clocks"]["hold"] = 1
        self.fixture.write("output_files/ap_core.sta.rpt", sta_report(unconstrained=counts).encode())
        with self.assertRaisesRegex(audit.AuditError, "nonzero unconstrained"):
            audit.audit(self.root)

    def test_native_and_detailed_unconstrained_summaries_are_exact(self) -> None:
        original = sta_report()
        title = "; Unconstrained Paths Summary ;"
        second_start = original.rfind(title)
        second_end = original.index("+ fixture +\n; Summary ;", second_start)
        second = original[second_start:second_end]
        mutations = (
            (
                original[:second_start] + original[second_end:],
                "expected exactly two report sections",
            ),
            (
                original[:second_end] + second + original[second_end:],
                "expected exactly two report sections",
            ),
            (
                original[:second_start]
                + second.replace(
                    "; Illegal Clocks ; 0 ; 0 ;",
                    "; Illegal Clocks ; 1 ; 0 ;",
                    1,
                )
                + original[second_end:],
                "nonzero unconstrained path counts",
            ),
        )
        for text, message in mutations:
            with self.subTest(message=message):
                self.fixture.write("output_files/ap_core.sta.rpt", text.encode())
                with self.assertRaisesRegex(audit.AuditError, message):
                    audit.audit(self.root)

    def test_exact_identity_version_status_and_resources_are_required(self) -> None:
        cases = (
            ("output_files/ap_core.map.rpt", "apf_top", "wrong_top", "top_level"),
            ("output_files/ap_core.fit.rpt", "Cyclone V", "Cyclone 10", "family"),
            ("output_files/ap_core.asm.rpt", "5CEBA4F23C8", "wrong", "device"),
            (
                "output_files/ap_core.sta.rpt",
                "Revision Name         ; ap_core",
                "Revision Name         ; other",
                "revision",
            ),
        )
        originals = {name: (self.root / name).read_bytes() for name, *_ in cases}
        for name, old, new, message in cases:
            with self.subTest(name=name):
                self.fixture.write(name, originals[name].replace(old.encode(), new.encode(), 1))
                with self.assertRaisesRegex(audit.AuditError, message):
                    audit.audit(self.root)
                self.fixture.write(name, originals[name])
        flow = (self.root / "output_files/ap_core.flow.rpt").read_bytes()
        self.fixture.write("output_files/ap_core.flow.rpt", flow.replace(b"Successful", b"Failed", 1))
        with self.assertRaisesRegex(audit.AuditError, "not successful"):
            audit.audit(self.root)
        self.fixture.write("output_files/ap_core.flow.rpt", flow)
        synthesis = (self.root / "output_files/ap_core.map.rpt").read_bytes()
        self.fixture.write(
            "output_files/ap_core.map.rpt",
            synthesis.replace(b"Successful", b"Failed", 1),
        )
        with self.assertRaisesRegex(audit.AuditError, "synthesis status"):
            audit.audit(self.root)
        self.fixture.write("output_files/ap_core.map.rpt", synthesis)
        tool = (self.root / "toolchain-version.txt").read_bytes()
        self.fixture.write("toolchain-version.txt", tool.replace(b"Build 850", b"Build 851"))
        with self.assertRaisesRegex(audit.AuditError, "21.1.1 Build 850"):
            audit.audit(self.root)
        self.fixture.write("toolchain-version.txt", tool)
        flow = (self.root / "output_files/ap_core.flow.rpt").read_bytes()
        self.fixture.write(
            "output_files/ap_core.flow.rpt",
            flow.replace(b"06/23/2022", b"06/24/2022"),
        )
        with self.assertRaisesRegex(audit.AuditError, "version lines disagree"):
            audit.audit(self.root)
        self.fixture.write("output_files/ap_core.flow.rpt", flow)
        self.fixture.write(
            "output_files/ap_core.flow.rpt",
            flow.replace(
                b"SJ Lite Edition",
                b"SJ Lite Edition Version 22.1 Build 1",
            ),
        )
        with self.assertRaisesRegex(audit.AuditError, "21.1.1 Build 850"):
            audit.audit(self.root)
        self.fixture.write("output_files/ap_core.flow.rpt", flow)
        fit = (self.root / "output_files/ap_core.fit.rpt").read_bytes()
        self.fixture.write("output_files/ap_core.fit.rpt", fit.replace(b"; Total PLLs ;", b"; Unknown PLLs ;"))
        with self.assertRaisesRegex(audit.AuditError, "fit plls"):
            audit.audit(self.root)

    def test_critical_warning_is_inventoried_but_candidate_fails(self) -> None:
        self.fixture.write("quartus.log", b"Critical Warning: assignment ignored\n")
        output = self.root / "candidate.json"
        self.assertEqual(audit.main(["--artifacts", str(self.root), "--output", str(output)]), 1)
        payload = json.loads(output.read_text())["quartus_audit"]
        self.assertFalse(payload["audit_pass"])
        self.assertEqual(payload["critical_warnings"]["count"], 1)
        self.assertFalse(payload["candidate_gates"]["no_critical_warnings"])
        self.assertFalse(payload["candidate_gates"]["pocket_hardware"])

    def test_incomplete_pll_self_reset_configuration_fails(self) -> None:
        self.fixture.write(
            "quartus.log",
            b'Warning (15069): PLL "core_pll" has self-reset on loss of lock '
            b"turned on. However, no value is specified for the gated lock counter.\n",
        )
        output = self.root / "candidate.json"
        self.assertEqual(
            audit.main(["--artifacts", str(self.root), "--output", str(output)]),
            1,
        )
        payload = json.loads(output.read_text())["quartus_audit"]
        self.assertFalse(payload["audit_pass"])
        self.assertEqual(payload["pll_self_reset_warnings"]["warning_id"], 15069)
        self.assertEqual(payload["pll_self_reset_warnings"]["count"], 1)
        self.assertFalse(payload["candidate_gates"]["pll_self_reset_configured"])
        self.assertFalse(payload["candidate_gates"]["pocket_hardware"])

    def test_unconnected_pll_reset_port_warning_fails(self) -> None:
        self.fixture.write(
            "quartus.log",
            b"Warning: RST port on the PLL is not properly connected to a "
            b"valid reset source.\n",
        )
        output = self.root / "candidate.json"
        self.assertEqual(
            audit.main(["--artifacts", str(self.root), "--output", str(output)]),
            1,
        )
        payload = json.loads(output.read_text())["quartus_audit"]
        self.assertFalse(payload["audit_pass"])
        self.assertEqual(payload["pll_reset_port_warnings"]["count"], 1)
        self.assertFalse(payload["candidate_gates"]["pll_reset_port_connected"])
        self.assertFalse(payload["candidate_gates"]["pocket_hardware"])

    def test_connectivity_warning_12241_requires_review_without_waiver(self) -> None:
        map_report = self.root / "output_files/ap_core.map.rpt"
        map_report.write_text(
            map_report.read_text()
            + "Warning (12241): 1 hierarchy have connectivity warnings - "
            "see the Connectivity Checks report folder\n"
            + '; Port Connectivity Checks: "fixture:unreviewed" ;\n'
            + "+ fixture +\n"
            + "; Port ; Type ; Severity ; Details ;\n"
            + "+ fixture +\n"
            + "; data ; Output ; Warning ; Declared but not connected ;\n"
            + "+ fixture +\n"
        )
        output = self.root / "candidate.json"

        self.assertEqual(
            audit.main(
                ["--artifacts", str(self.root), "--output", str(output)]
            ),
            1,
        )
        payload = json.loads(output.read_text())["quartus_audit"]
        self.assertFalse(payload["audit_pass"])
        self.assertTrue(payload["candidate_gates"]["no_critical_warnings"])
        self.assertFalse(payload["candidate_gates"]["no_connectivity_warnings"])
        self.assertFalse(
            payload["candidate_gates"]["connectivity_warnings_reviewed"]
        )
        self.assertEqual(payload["connectivity_warnings"]["warning_id"], 12241)
        self.assertEqual(payload["connectivity_warnings"]["count"], 1)
        self.assertTrue(payload["connectivity_warnings"]["review_required"])
        self.assertEqual(
            payload["connectivity_warnings"]["exact_review"]["status"],
            "rejected_exact_set",
        )
        self.assertEqual(
            payload["artifacts"]["output_files/ap_core.map.rpt"],
            audit.digest(map_report),
        )

    def test_exact_source_bound_connectivity_set_passes_review_gate(self) -> None:
        map_path = self.root / "output_files/ap_core.map.rpt"
        map_path.write_text(
            map_path.read_text() + reviewed_connectivity_report(),
            encoding="utf-8",
        )
        payload = audit.audit(self.root)["quartus_audit"]
        self.assertTrue(payload["audit_pass"])
        self.assertFalse(payload["candidate_gates"]["no_connectivity_warnings"])
        self.assertTrue(
            payload["candidate_gates"]["connectivity_warnings_reviewed"]
        )
        self.assertFalse(payload["connectivity_warnings"]["review_required"])
        exact = payload["connectivity_warnings"]["exact_review"]
        self.assertTrue(exact["accepted"])
        self.assertEqual(exact["status"], "accepted_exact_set")
        self.assertEqual(exact["observed"]["warning_rows"], 121)
        self.assertEqual(exact["differences"]["unexpected"], [])

        self.fixture.write(
            "quartus.log",
            b"Warning (12241): unreviewed alternate summary text\n",
        )
        rejected = audit.audit(self.root)["quartus_audit"]
        self.assertFalse(rejected["audit_pass"])
        self.assertEqual(
            rejected["connectivity_warnings"]["exact_review"]["status"],
            "rejected_summary_entries",
        )

    def test_map_report_is_required_for_successful_candidate(self) -> None:
        map_report = self.root / "output_files/ap_core.map.rpt"
        map_report.unlink()
        with self.assertRaisesRegex(
            audit.AuditError, "missing regular artifact: output_files/ap_core.map.rpt"
        ):
            audit.audit(self.root)

    def test_map_settings_device_is_exact_and_timing_completion_is_required(self) -> None:
        self.fixture.write(
            "output_files/ap_core.map.rpt",
            map_report(device="5CEBA4F23C7").encode(),
        )
        with self.assertRaisesRegex(audit.AuditError, "synthesis device"):
            audit.audit(self.root)

        self.fixture.write("output_files/ap_core.map.rpt", map_report().encode())
        sta = (self.root / "output_files/ap_core.sta.rpt").read_text()
        self.fixture.write(
            "output_files/ap_core.sta.rpt",
            sta.replace("was successful. 0 errors", "was unsuccessful. 1 errors").encode(),
        )
        with self.assertRaisesRegex(audit.AuditError, "timing analysis completion"):
            audit.audit(self.root)

    def test_empty_or_symlink_artifact_and_bad_rbf_hash_fail(self) -> None:
        rbf = self.root / "output_files/ap_core.rbf"
        rbf.unlink()
        rbf.symlink_to(self.root / "build_id.mif")
        with self.assertRaisesRegex(audit.AuditError, "symlink"):
            audit.audit(self.root)
        rbf.unlink()
        self.fixture.write("output_files/ap_core.rbf", b"changed")
        with self.assertRaisesRegex(audit.AuditError, "does not match"):
            audit.audit(self.root)

    def test_unknown_timing_format_and_missing_analysis_fail(self) -> None:
        text = sta_report().replace("; Slack ;", "; Delay ;", 1)
        self.fixture.write("output_files/ap_core.sta.rpt", text.encode())
        with self.assertRaisesRegex(audit.AuditError, "unknown setup"):
            audit.audit(self.root)
        text = sta_report().replace("; Slow 1100mV 85C Model Removal Summary ;", "; Unsupported Removal Data ;")
        self.fixture.write("output_files/ap_core.sta.rpt", text.encode())
        with self.assertRaisesRegex(
            audit.AuditError, "missing or unexpected removal timing corners"
        ):
            audit.audit(self.root)


if __name__ == "__main__":
    unittest.main()
