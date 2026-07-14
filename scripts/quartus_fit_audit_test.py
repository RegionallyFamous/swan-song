#!/usr/bin/env python3

import json
from pathlib import Path
import tempfile
import unittest

import quartus_fit_audit as audit
import quartus_container_provenance as container_provenance


VERSION = "Version 21.1.1 Build 850 06/23/2021 SJ Lite Edition"
IMAGE_ID = "sha256:" + "a" * 64

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
+-----------------------+----------------+---------------------+
"""


def sta_report(slacks=None, clocks=None, unconstrained=None, no_path_analyses=()) -> str:
    slacks = slacks or {name: "0.100" for name in audit.ANALYSES}
    clocks = clocks or list(audit.REQUIRED_CLOCKS) + ["pll_core"]
    unconstrained = unconstrained or {
        name: {"setup": 0, "hold": 0}
        for name in audit.UNCONSTRAINED_PROPERTIES
    }
    text = f"""Timing Analyzer report for ap_core
Quartus Prime Version 21.1.1 Build 850 06/23/2021 SJ Lite Edition

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
    for analysis in audit.ANALYSES:
        text += f"; Slow 1100mV 85C Model {analysis.title()} Summary ;\n"
        if analysis in no_path_analyses:
            text += "No paths to report.\n"
            continue
        text += f"""; Clock ; Slack ; End Point TNS ;
; clk_74a ; {slacks[analysis]} ; 0.000 ;
"""
    text += "; Unconstrained Paths Summary ;\n; Property ; Setup ; Hold ;\n"
    for property_name in audit.UNCONSTRAINED_PROPERTIES:
        display = property_name.title()
        text += (
            f"; {display} ; {unconstrained[property_name]['setup']} ; "
            f"{unconstrained[property_name]['hold']} ;\n"
        )
    text += (
        "; Timing Analyzer Messages ;\n"
        "Info: Quartus Prime Timing Analyzer was successful. 0 errors, 0 warnings\n"
    )
    return text


class Fixture:
    def __init__(self, root: Path):
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
; Total PLLs ; 4 / 6 (67%) ;
"""
        self.write("output_files/ap_core.fit.rpt", fit.encode())
        self.write(
            "output_files/ap_core.asm.rpt",
            report("Assembler Summary", "Assembler Status").encode(),
        )
        self.write("output_files/ap_core.sta.rpt", sta_report().encode())
        self.write("toolchain-version.txt", f"Quartus Prime Shell\n{VERSION}\n".encode())
        self.write(
            "build-metadata.txt",
            (
                "source_commit=" + "a" * 40 + "\n"
                "source_date_epoch=1700000000\n"
                "platform=linux/amd64\n"
                "quartus=21.1.1.850 Lite\n"
                "device=5CEBA4F23C8\n"
            ).encode(),
        )
        self.write("build_id.mif", b"WIDTH=32; DEPTH=8; CONTENT BEGIN END;\n")
        self.write("quartus.log", b"Info: Full Compilation was successful\n")
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
            payload["timing"]["clocks"]["required"], list(audit.REQUIRED_CLOCKS)
        )
        self.assertEqual(
            set(payload["timing"]["unconstrained_paths"]),
            set(audit.UNCONSTRAINED_PROPERTIES),
        )
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
        self.assertEqual(set(payload["artifacts"]), set(audit.REQUIRED_ARTIFACTS))
        self.assertIn("container-provenance.json", payload["artifacts"])
        self.assertIn("container-packages.tsv", payload["artifacts"])
        self.assertNotIn("release_evidence", json.loads(first))

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

        for analysis in ("setup", "hold"):
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
            flow.replace(b"06/23/2021", b"06/24/2021"),
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

    def test_connectivity_warning_12241_requires_review_without_waiver(self) -> None:
        map_report = self.root / "output_files/ap_core.map.rpt"
        map_report.write_text(
            map_report.read_text()
            + "Warning (12241): 31 hierarchies have connectivity warnings - "
            "see the Connectivity Checks report folder\n"
            + "; Connectivity Checks ;\n"
            + "; Port ; Type ; Severity ; Details ;\n"
            + "; data ; Output ; Warning ; Declared but not connected ;\n"
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
        self.assertEqual(payload["connectivity_warnings"]["warning_id"], 12241)
        self.assertEqual(payload["connectivity_warnings"]["count"], 1)
        self.assertTrue(payload["connectivity_warnings"]["review_required"])
        self.assertEqual(
            payload["artifacts"]["output_files/ap_core.map.rpt"],
            audit.digest(map_report),
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
        with self.assertRaisesRegex(audit.AuditError, "missing removal"):
            audit.audit(self.root)


if __name__ == "__main__":
    unittest.main()
