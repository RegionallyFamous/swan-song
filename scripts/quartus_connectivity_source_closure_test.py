#!/usr/bin/env python3
"""Tests for deterministic, fail-closed Quartus source-closure discovery."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import quartus_connectivity_source_closure as closure


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID_GENERATOR_TEXT = (ROOT / closure.BUILD_ID_GENERATOR).read_text(
    encoding="utf-8"
)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


class ProjectFixture:
    def __init__(self, root: Path, qsf: str | None = None) -> None:
        self.root = root
        self.repo = root / "repo"
        self.fpga = self.repo / "src/fpga"
        self.fpga.mkdir(parents=True)
        (self.fpga / "ap_core.qpf").write_text(
            'PROJECT_REVISION = "ap_core"\n', encoding="utf-8"
        )
        (self.fpga / "ap_core_assignment_defaults.qdf").write_text(
            "# defaults\n", encoding="utf-8"
        )
        (self.fpga / "ap_core.qsf").write_text(
            qsf or "set_global_assignment -name VERILOG_FILE top.v\n",
            encoding="utf-8",
        )
        (self.fpga / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
        _git(self.repo, "init")

    def write(self, relative: str, value: str) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return path

    def commit(self, message: str = "fixture") -> str:
        _git(self.repo, "add", ".")
        _git(
            self.repo,
            "-c",
            "user.name=Swan Song Test",
            "-c",
            "user.email=swan-song@example.invalid",
            "commit",
            "-m",
            message,
        )
        return _git(self.repo, "rev-parse", "HEAD")


class QuartusConnectivitySourceClosureTest(unittest.TestCase):
    def test_recursive_qip_closure_is_sorted_complete_and_deterministic(self) -> None:
        qsf = "\n".join(
            (
                "set_global_assignment -name GENERATE_RBF_FILE ON",
                "set_global_assignment -name SLD_FILE db/generated.stp",
                'set_global_assignment -name PRE_FLOW_SCRIPT_FILE '
                '"quartus_sh:apf/build_id_gen.tcl"',
                "set_global_assignment -name VERILOG_FILE top.v",
                "set_global_assignment -name QIP_FILE ip/outer.qip",
                "set_global_assignment -name SIGNALTAP_FILE debug.stp",
                "set_global_assignment -name USE_SIGNALTAP_FILE debug.stp",
                "",
            )
        )
        with tempfile.TemporaryDirectory(prefix="quartus-closure-") as temporary:
            fixture = ProjectFixture(Path(temporary), qsf)
            fixture.write(closure.BUILD_ID_GENERATOR, BUILD_ID_GENERATOR_TEXT)
            fixture.write(closure.BUILD_ID_MIF, "-- generated placeholder\n")
            fixture.write("src/fpga/debug.stp", "debug\n")
            fixture.write(
                "src/fpga/ip/outer.qip",
                "\n".join(
                    (
                        "set_global_assignment -name QIP_FILE "
                        '[file join $::quartus(qip_path) "inner.qip"]',
                        "set_global_assignment -name SDC_FILE "
                        '[file join $::quartus(qip_path) "timing.sdc"]',
                        "",
                    )
                ),
            )
            fixture.write("src/fpga/ip/timing.sdc", "create_clock -period 10 clk\n")
            fixture.write(
                "src/fpga/ip/inner.qip",
                "\n".join(
                    (
                        'set_global_assignment -library "fixture" '
                        "-name SYSTEMVERILOG_FILE "
                        '[file join $::quartus(qip_path) "inner.sv"]',
                        "set_global_assignment -name MISC_FILE "
                        '[file join $::quartus(qip_path) "missing.ppf"]',
                        "",
                    )
                ),
            )
            fixture.write("src/fpga/ip/inner.sv", "module inner; endmodule\n")
            commit = fixture.commit()

            first = closure.discover_source_paths(fixture.repo)
            second = closure.discover_source_paths(fixture.repo)
            self.assertEqual(first, second)
            self.assertEqual(first, tuple(sorted(set(first))))
            self.assertIn("src/fpga/ip/inner.qip", first)
            self.assertIn("src/fpga/ip/inner.sv", first)
            self.assertIn("src/fpga/ip/timing.sdc", first)
            self.assertNotIn("src/fpga/db/generated.stp", first)
            self.assertNotIn("src/fpga/ip/missing.ppf", first)

            bindings, identity = closure.committed_bindings(fixture.repo, commit)
            self.assertEqual(set(bindings), set(first))
            self.assertEqual(identity, closure.closure_identity(first))
            self.assertEqual(identity["algorithm"], closure.MAGIC)

    def test_literal_read_sdc_is_recursive_and_dynamic_loaders_fail_closed(self) -> None:
        qsf = "set_global_assignment -name SDC_FILE apf/root.sdc\n"
        with tempfile.TemporaryDirectory(prefix="quartus-closure-sdc-") as temporary:
            fixture = ProjectFixture(Path(temporary), qsf)
            fixture.write(
                "src/fpga/apf/root.sdc",
                'read_sdc "core/nested.sdc"\n',
            )
            fixture.write(
                "src/fpga/core/nested.sdc",
                "create_clock -period 10 [get_ports clk]\n",
            )
            fixture.commit()
            paths = closure.discover_source_paths(fixture.repo)
            self.assertIn("src/fpga/apf/root.sdc", paths)
            self.assertIn("src/fpga/core/nested.sdc", paths)

        cases = (
            "read_sdc $dynamic_path\n",
            'source "core/hidden.sdc"\n',
            'if {1} { read_sdc "core/hidden.sdc" }\n',
            'read_verilog "core/hidden.v"\n',
            '$loader "core/hidden.sdc"\n',
        )
        for contents in cases:
            with self.subTest(contents=contents), tempfile.TemporaryDirectory(
                prefix="quartus-closure-sdc-dynamic-"
            ) as temporary:
                fixture = ProjectFixture(Path(temporary), qsf)
                fixture.write("src/fpga/apf/root.sdc", contents)
                fixture.write("src/fpga/core/hidden.sdc", "# hidden\n")
                fixture.write("src/fpga/core/hidden.v", "module hidden; endmodule\n")
                fixture.commit()
                with self.assertRaisesRegex(closure.ClosureError, "dynamic.*SDC"):
                    closure.discover_source_paths(fixture.repo)

    def test_real_apf_sdc_resolves_from_project_directory(self) -> None:
        relative = "src/fpga/apf/apf_constraints.sdc"
        dependencies = closure._sdc_dependencies(  # noqa: SLF001
            (ROOT / relative).read_bytes(),
            source_root=ROOT,
            fpga_root=ROOT / "src/fpga",
            relative=relative,
        )
        self.assertEqual(
            dependencies,
            ("src/fpga/core/core_constraints.sdc",),
        )

    def test_qip_cycles_terminate_without_hiding_inputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quartus-closure-cycle-") as temporary:
            fixture = ProjectFixture(
                Path(temporary),
                "set_global_assignment -name QIP_FILE ip/a.qip\n",
            )
            fixture.write(
                "src/fpga/ip/a.qip",
                'set_global_assignment -name QIP_FILE [file join $::quartus(qip_path) "b.qip"]\n',
            )
            fixture.write(
                "src/fpga/ip/b.qip",
                'set_global_assignment -name QIP_FILE [file join $::quartus(qip_path) "a.qip"]\n',
            )
            fixture.commit()
            paths = closure.discover_source_paths(fixture.repo)
            self.assertIn("src/fpga/ip/a.qip", paths)
            self.assertIn("src/fpga/ip/b.qip", paths)

    def test_untracked_missing_symlink_and_escape_inputs_fail_closed(self) -> None:
        mutations = {
            "untracked": "set_global_assignment -name VERILOG_FILE new.v\n",
            "missing": "set_global_assignment -name VERILOG_FILE absent.v\n",
            "escape": "set_global_assignment -name VERILOG_FILE ../outside.v\n",
        }
        for name, assignment in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix=f"quartus-closure-{name}-"
            ) as temporary:
                fixture = ProjectFixture(Path(temporary), assignment)
                if name == "untracked":
                    fixture.commit()
                    fixture.write("src/fpga/new.v", "module new; endmodule\n")
                else:
                    fixture.commit()
                with self.assertRaises(closure.ClosureError):
                    closure.discover_source_paths(fixture.repo)

        with tempfile.TemporaryDirectory(prefix="quartus-closure-link-") as temporary:
            fixture = ProjectFixture(Path(temporary))
            target = fixture.fpga / "real.v"
            target.write_text("module real; endmodule\n", encoding="utf-8")
            (fixture.fpga / "top.v").unlink()
            (fixture.fpga / "top.v").symlink_to("real.v")
            fixture.commit()
            with self.assertRaisesRegex(closure.ClosureError, "symlink"):
                closure.discover_source_paths(fixture.repo)

    def test_unknown_file_assignment_fails_instead_of_escaping_closure(self) -> None:
        cases = (
            (
                "set_global_assignment -name FUTURE_FILE hidden.v\n",
                "unreviewed Quartus file assignment",
            ),
            (
                "set_global_assignment -section_id fixture "
                "-name VERILOG_FILE hidden.v\n",
                "unsupported syntax for Quartus file assignment",
            ),
        )
        for qsf, error in cases:
            with self.subTest(qsf=qsf), tempfile.TemporaryDirectory(
                prefix="quartus-closure-unknown-"
            ) as temporary:
                fixture = ProjectFixture(Path(temporary), qsf)
                fixture.write("src/fpga/hidden.v", "module hidden; endmodule\n")
                fixture.commit()
                with self.assertRaisesRegex(closure.ClosureError, error):
                    closure.discover_source_paths(fixture.repo)

    def test_tcl_indirection_continuation_and_substitution_fail_closed(self) -> None:
        cases = (
            (
                "source",
                "source extra.qsf\n",
                "unsupported Tcl command",
                {
                    "src/fpga/extra.qsf": (
                        "set_global_assignment -name SYSTEMVERILOG_FILE hidden.sv\n"
                    ),
                    "src/fpga/hidden.sv": "module hidden; endmodule\n",
                },
            ),
            (
                "continuation",
                "set_global_assignment \\\n+  -name SYSTEMVERILOG_FILE hidden.sv\n",
                "continuations and escapes",
                {"src/fpga/hidden.sv": "module hidden; endmodule\n"},
            ),
            (
                "substitution",
                "set name hidden\n"
                "set_global_assignment -name SYSTEMVERILOG_FILE dir/$name.sv\n",
                "unsupported Tcl command",
                {
                    "src/fpga/dir/$name.sv": "module decoy; endmodule\n",
                    "src/fpga/dir/hidden.sv": "module hidden; endmodule\n",
                },
            ),
        )
        for name, qsf, error, files in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix=f"quartus-closure-tcl-{name}-"
            ) as temporary:
                fixture = ProjectFixture(Path(temporary), qsf)
                for relative, value in files.items():
                    fixture.write(relative, value)
                fixture.commit()
                with self.assertRaisesRegex(closure.ClosureError, error):
                    closure.discover_source_paths(fixture.repo)

    def test_assignment_names_are_case_insensitive_without_hiding_inputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quartus-closure-case-") as temporary:
            fixture = ProjectFixture(
                Path(temporary),
                "set_global_assignment -name systemverilog_file hidden.sv\n",
            )
            fixture.write("src/fpga/hidden.sv", "module hidden; endmodule\n")
            fixture.commit()
            self.assertIn(
                "src/fpga/hidden.sv", closure.discover_source_paths(fixture.repo)
            )

    def test_hdl_include_and_search_paths_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quartus-closure-include-") as temporary:
            fixture = ProjectFixture(Path(temporary))
            fixture.write(
                "src/fpga/top.v",
                '`include "defs.vh"\nmodule top; wire [`WIDTH-1:0] x; endmodule\n',
            )
            fixture.write("src/fpga/defs.vh", "`define WIDTH 4\n")
            fixture.commit()
            with self.assertRaisesRegex(closure.ClosureError, "HDL includes"):
                closure.discover_source_paths(fixture.repo)

        with tempfile.TemporaryDirectory(
            prefix="quartus-closure-include-nonstandard-suffix-"
        ) as temporary:
            fixture = ProjectFixture(
                Path(temporary),
                "set_global_assignment -name VERILOG_FILE top.design\n",
            )
            fixture.write("src/fpga/top.design", '`include "hidden.vh"\n')
            fixture.write("src/fpga/hidden.vh", "`define HIDDEN 1\n")
            fixture.commit()
            with self.assertRaisesRegex(closure.ClosureError, "HDL includes"):
                closure.discover_source_paths(fixture.repo)

        with tempfile.TemporaryDirectory(prefix="quartus-closure-search-") as temporary:
            fixture = ProjectFixture(
                Path(temporary),
                "set_global_assignment -name SEARCH_PATH include\n"
                "set_global_assignment -name VERILOG_FILE top.v\n",
            )
            fixture.commit()
            with self.assertRaisesRegex(closure.ClosureError, "search-path"):
                closure.discover_source_paths(fixture.repo)

    def test_unbound_runtime_memory_inputs_fail_closed(self) -> None:
        cases = (
            'module top; initial $readmemh("image.hex", memory); endmodule\n',
            'module top; localparam string init_file = "image.mif"; endmodule\n',
        )
        for source in cases:
            with self.subTest(source=source), tempfile.TemporaryDirectory(
                prefix="quartus-closure-runtime-input-"
            ) as temporary:
                fixture = ProjectFixture(Path(temporary))
                fixture.write("src/fpga/top.v", source)
                fixture.commit()
                with self.assertRaises(closure.ClosureError):
                    closure.discover_source_paths(fixture.repo)

    def test_build_id_generator_consumer_contract_is_exact(self) -> None:
        qsf = (
            'set_global_assignment -name PRE_FLOW_SCRIPT_FILE '
            '"quartus_sh:apf/build_id_gen.tcl"\n'
            "set_global_assignment -name VERILOG_FILE apf/mf_datatable.v\n"
        )
        consumer = (
            "module mf_datatable;\n"
            'altsyncram_component.init_file = "./apf/build_id.mif",\n'
            "endmodule\n"
        )
        with tempfile.TemporaryDirectory(prefix="quartus-closure-build-id-") as temporary:
            fixture = ProjectFixture(Path(temporary), qsf)
            fixture.write(closure.BUILD_ID_GENERATOR, BUILD_ID_GENERATOR_TEXT)
            fixture.write("src/fpga/apf/mf_datatable.v", consumer)
            fixture.write("src/fpga/apf/build_id.mif", "-- generated placeholder\n")
            fixture.commit()

            paths = closure.discover_source_paths(fixture.repo)
            self.assertIn("src/fpga/apf/build_id_gen.tcl", paths)
            self.assertIn("src/fpga/apf/mf_datatable.v", paths)
            self.assertNotIn("src/fpga/apf/build_id.mif", paths)

            fixture.write(
                closure.BUILD_ID_GENERATOR,
                BUILD_ID_GENERATOR_TEXT + "\n# mutation\n",
            )
            with self.assertRaisesRegex(closure.ClosureError, "generator changed"):
                closure.discover_source_paths(fixture.repo)

    def test_unreviewed_pre_flow_script_fails_closed(self) -> None:
        qsf = (
            'set_global_assignment -name PRE_FLOW_SCRIPT_FILE '
            '"quartus_sh:other.tcl"\n'
        )
        with tempfile.TemporaryDirectory(prefix="quartus-closure-pre-flow-") as temporary:
            fixture = ProjectFixture(Path(temporary), qsf)
            fixture.write("src/fpga/other.tcl", "# arbitrary pre-flow\n")
            fixture.commit()
            with self.assertRaisesRegex(closure.ClosureError, "only the exact reviewed"):
                closure.discover_source_paths(fixture.repo)

    def test_inactive_blank_dpram_init_exception_cannot_become_referenced(self) -> None:
        qsf = "set_global_assignment -name VHDL_FILE core/rtl/dpram.vhd\n"
        dpram = "\n".join(
            (
                "entity dpram_dif is",
                'generic (mem_init_file : string := " ");',
                "end entity;",
                "architecture syn of dpram_dif is",
                "begin",
                "init_file => mem_init_file,",
                "end syn;",
                "",
            )
        )
        with tempfile.TemporaryDirectory(prefix="quartus-closure-dpram-") as temporary:
            fixture = ProjectFixture(Path(temporary), qsf)
            fixture.write("src/fpga/core/rtl/dpram.vhd", dpram)
            fixture.commit()
            closure.discover_source_paths(fixture.repo)

            qsf_path = fixture.fpga / "ap_core.qsf"
            qsf_path.write_text(
                qsf + "set_global_assignment -name VHDL_FILE uses_dpram.vhd\n",
                encoding="utf-8",
            )
            fixture.write(
                "src/fpga/uses_dpram.vhd",
                "architecture rtl of fixture is begin "
                "ram: entity work.dpram_dif; end rtl;\n",
            )
            fixture.commit("reference dpram_dif")
            with self.assertRaisesRegex(closure.ClosureError, "referenced or changed"):
                closure.discover_source_paths(fixture.repo)

    def test_committed_bindings_reject_dirty_closure_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quartus-closure-drift-") as temporary:
            fixture = ProjectFixture(Path(temporary))
            commit = fixture.commit()
            top = fixture.fpga / "top.v"
            top.write_text("module top; wire dirty; endmodule\n", encoding="utf-8")
            with self.assertRaisesRegex(closure.ClosureError, "drifts"):
                closure.committed_bindings(fixture.repo, commit)

            current, identity = closure.current_bindings(fixture.repo)
            self.assertEqual(
                current["src/fpga/top.v"], hashlib.sha256(top.read_bytes()).hexdigest()
            )
            self.assertEqual(identity["paths"], 4)

    def test_committed_graph_is_parsed_from_commit_not_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quartus-closure-commit-graph-") as temporary:
            fixture = ProjectFixture(Path(temporary))
            commit = fixture.commit()
            (fixture.fpga / "ap_core.qsf").write_text(
                "source unreviewed.qsf\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(closure.ClosureError, "drifts"):
                closure.committed_bindings(fixture.repo, commit)

    def test_descriptor_reader_rejects_content_and_inode_swaps(self) -> None:
        mutations = ("overwrite", "replace")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                prefix=f"quartus-closure-reader-{mutation}-"
            ) as temporary:
                fixture = ProjectFixture(Path(temporary))
                fixture.commit()
                target = fixture.fpga / "top.v"
                original_read = os.read
                changed = False

                def mutate_after_read(descriptor: int, count: int) -> bytes:
                    nonlocal changed
                    value = original_read(descriptor, count)
                    if value and not changed:
                        changed = True
                        if mutation == "overwrite":
                            target.write_text(
                                "module changed; endmodule\n", encoding="utf-8"
                            )
                        else:
                            old = target.with_name("top.old")
                            target.rename(old)
                            target.write_text(
                                "module replacement; endmodule\n", encoding="utf-8"
                            )
                    return value

                with closure._WorktreeReader(fixture.repo) as reader:  # noqa: SLF001
                    with mock.patch.object(
                        closure.os, "read", side_effect=mutate_after_read
                    ):
                        with self.assertRaisesRegex(
                            closure.ClosureError, "changed while reading"
                        ):
                            reader.read(
                                "src/fpga/top.v",
                                "fixture source",
                                closure.MAX_SOURCE_FILE_BYTES,
                            )


if __name__ == "__main__":
    unittest.main()
