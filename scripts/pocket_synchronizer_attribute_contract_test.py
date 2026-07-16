#!/usr/bin/env python3
"""Mutation-lock every Intel-native synchronizer assignment in Pocket RTL."""

from __future__ import annotations

from collections import Counter
import pathlib
import re
from typing import Mapping


ROOT = pathlib.Path(__file__).resolve().parents[1]
RTL_ROOT = ROOT / "src/fpga"
RTL_SUFFIXES = {".sv", ".v", ".vh", ".vhd"}

NATIVE_VALUE = (
    "-name SYNCHRONIZER_IDENTIFICATION FORCED; "
    "-name PRESERVE_REGISTER ON"
)
NATIVE_ATTRIBUTE = f'(* altera_attribute = "{NATIVE_VALUE}" *)'

# These are declarations, rather than loose signal names, so a renamed,
# resized, reinitialized, duplicated, or incorrectly attached synchronizer is
# rejected. Whitespace is normalized when the contract is evaluated.
EXPECTED_DECLARATIONS: dict[str, tuple[str, ...]] = {
    "src/fpga/core/apf_input_blocked_cdc.sv": (
        "reg acknowledge_meta_source = 1'b0;",
        "reg acknowledge_sync_source = 1'b0;",
        "reg request_meta_destination = 1'b0;",
        "reg request_sync_destination = 1'b0;",
    ),
    "src/fpga/core/apf_menu_focus_cdc.sv": (
        "reg menu_focus_meta = 1'b0;",
        "reg menu_focus_sync = 1'b0;",
        "reg menu_focus_level = 1'b0;",
    ),
    "src/fpga/core/apf_reset_sync.sv": (
        "reg [STAGES-1:0] sync_chain = {STAGES{1'b0}};",
    ),
    "src/fpga/core/apf_rom_plan_cdc.sv": (
        "reg [1:0] source_reset_sync = 2'b00;",
        "reg [1:0] memory_reset_sync = 2'b00;",
        "reg [1:0] system_reset_sync = 2'b00;",
        "reg acknowledge_mem_meta;",
        "reg acknowledge_mem_sync;",
        "reg acknowledge_sys_meta;",
        "reg acknowledge_sys_sync;",
        "reg request_mem_meta;",
        "reg request_mem_sync;",
        "reg request_sys_meta;",
        "reg request_sys_sync;",
    ),
    "src/fpga/core/apf_rtc_cdc.sv": (
        "reg [1:0] source_reset_sync = 2'b00;",
        "reg [1:0] destination_reset_sync = 2'b00;",
        "reg acknowledge_meta;",
        "reg acknowledge_sync;",
        "reg request_meta;",
        "reg request_sync;",
    ),
    "src/fpga/core/apf_save_metadata_cdc.sv": (
        "reg [1:0] source_reset_sync = 2'b00;",
        "reg [1:0] destination_reset_sync = 2'b00;",
        "reg acknowledge_meta;",
        "reg acknowledge_sync;",
        "reg request_meta;",
        "reg request_sync;",
    ),
    "src/fpga/core/apf_scaler_selector.sv": (
        "reg [1:0] sys_reset_sync;",
        "reg [1:0] video_reset_sync;",
        "reg acknowledge_meta_sys;",
        "reg acknowledge_sync_sys;",
        "reg request_meta_video;",
        "reg request_sync_video;",
    ),
    "src/fpga/core/apf_settings_cdc.sv": (
        "reg [1:0] source_reset_sync;",
        "reg [1:0] destination_reset_sync;",
        "reg acknowledge_meta_source;",
        "reg acknowledge_sync_source;",
        "reg request_meta_destination;",
        "reg request_sync_destination;",
    ),
    "src/fpga/core/apf_startup_sequencer.sv": (
        "reg [2:0] reset_sync;",
        "reg [2:0] host_reset_sync;",
    ),
    "src/fpga/core/wonderswan.sv": (
        "reg [2:0] clearing_save_sys_sync = 3'b111;",
    ),
}

ATTRIBUTE_DECLARATION = re.compile(
    r"\(\*\s*altera_attribute\s*=\s*\"(?P<value>[^\"]*)\"\s*\*\)"
    r"\s*(?P<declaration>reg\b[^;]*;)",
    re.DOTALL,
)
ATTRIBUTE_IDENTIFIER = re.compile(r"\baltera_attribute\b")
UNSUPPORTED_ASYNC_REG = re.compile(r"\bASYNC_REG\b", re.IGNORECASE)


class ContractError(ValueError):
    """The exact synchronizer attribute contract was violated."""


def compact_declaration(declaration: str) -> str:
    return re.sub(r"\s+", "", declaration)


def compact_value(value: str) -> str:
    return " ".join(value.split())


def load_sources() -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(RTL_ROOT.rglob("*"))
        if path.is_file() and path.suffix.lower() in RTL_SUFFIXES
    }


def verify_contract(sources: Mapping[str, str]) -> None:
    expected_files = set(EXPECTED_DECLARATIONS)
    missing_files = sorted(expected_files - set(sources))
    if missing_files:
        raise ContractError(f"expected RTL source file(s) missing: {missing_files!r}")

    failures: list[str] = []
    # Scan the complete FPGA RTL tree. This makes an ASYNC_REG or an additional
    # native assignment in a newly added source file fail until the exact-site
    # inventory is deliberately reviewed and updated.
    for relative in sorted(sources):
        expected_declarations = EXPECTED_DECLARATIONS.get(relative, ())
        source = sources[relative]
        if UNSUPPORTED_ASYNC_REG.search(source):
            failures.append(f"{relative}: unsupported ASYNC_REG remains")

        matches = list(ATTRIBUTE_DECLARATION.finditer(source))
        identifier_count = len(ATTRIBUTE_IDENTIFIER.findall(source))
        if identifier_count != len(matches):
            failures.append(
                f"{relative}: found {identifier_count} altera_attribute identifier(s) "
                f"but only {len(matches)} valid inferred-register assignment(s)"
            )

        expected = Counter(
            (NATIVE_VALUE, compact_declaration(declaration))
            for declaration in expected_declarations
        )
        actual = Counter(
            (
                compact_value(match.group("value")),
                compact_declaration(match.group("declaration")),
            )
            for match in matches
        )
        for record, count in sorted((expected - actual).items()):
            value, declaration = record
            failures.append(
                f"{relative}: missing {count} exact assignment(s): "
                f"{value!r} on {declaration!r}"
            )
        for record, count in sorted((actual - expected).items()):
            value, declaration = record
            failures.append(
                f"{relative}: unexpected {count} assignment(s): "
                f"{value!r} on {declaration!r}"
            )

    if failures:
        raise ContractError("\n".join(failures))


def must_reject(
    sources: Mapping[str, str],
    relative: str,
    old: str,
    new: str,
    label: str,
) -> None:
    if old not in sources[relative]:
        raise AssertionError(
            f"mutation fixture {label!r} is stale for {relative}: {old!r}"
        )
    mutated = dict(sources)
    mutated[relative] = mutated[relative].replace(old, new, 1)
    try:
        verify_contract(mutated)
    except ContractError:
        return
    raise AssertionError(f"invalid synchronizer mutation passed: {label}")


def main() -> None:
    expected_site_count = sum(map(len, EXPECTED_DECLARATIONS.values()))
    if len(EXPECTED_DECLARATIONS) != 10 or expected_site_count != 46:
        raise AssertionError(
            "test inventory must enumerate exactly 46 sites across ten RTL files"
        )

    sources = load_sources()
    verify_contract(sources)

    mutations = 0

    # Every affected file must reject a missing native assignment.
    for relative in EXPECTED_DECLARATIONS:
        must_reject(
            sources,
            relative,
            NATIVE_ATTRIBUTE,
            "",
            f"missing native assignment in {relative}",
        )
        mutations += 1

    # Exercise every syntactic/token class used by the native assignment.
    token_mutations = (
        ("(* altera_attribute", "/* altera_attribute", "attribute delimiter"),
        ("altera_attribute", "foreign_attribute", "attribute identifier"),
        ('= "-name', "= '-name", "string delimiter"),
        ("-name SYNCHRONIZER", "-option SYNCHRONIZER", "assignment introducer"),
        (
            "SYNCHRONIZER_IDENTIFICATION",
            "SYNCHRONIZER_DETECTION",
            "synchronizer option",
        ),
        ("FORCED; -name", "AUTO; -name", "synchronizer value"),
        ("FORCED; -name", "FORCED, -name", "assignment separator"),
        ("PRESERVE_REGISTER", "REMOVE_DUPLICATE_REGISTERS", "preserve option"),
        ("PRESERVE_REGISTER ON", "PRESERVE_REGISTER OFF", "preserve value"),
    )
    token_file = "src/fpga/core/apf_input_blocked_cdc.sv"
    for old, new, label in token_mutations:
        must_reject(sources, token_file, old, new, label)
        mutations += 1

    must_reject(
        sources,
        token_file,
        NATIVE_ATTRIBUTE,
        f'{NATIVE_ATTRIBUTE}\n  (* ASYNC_REG = "TRUE" *)',
        "unsupported ASYNC_REG",
    )
    mutations += 1

    first_declaration = EXPECTED_DECLARATIONS[token_file][0]
    must_reject(
        sources,
        token_file,
        first_declaration,
        first_declaration + f"\n  {NATIVE_ATTRIBUTE} reg unexpected_sync_stage;",
        "extra native assignment",
    )
    mutations += 1

    print(
        "PASS Intel-native synchronizer attributes "
        f"files={len(EXPECTED_DECLARATIONS)} sites={expected_site_count} "
        f"mutations={mutations}"
    )


if __name__ == "__main__":
    main()
