#!/usr/bin/env python3
"""Mutation-test the Pocket nonvolatile cartridge-size source contract."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parent.parent
WONDERSWAN = Path("src/fpga/core/wonderswan.sv")
CORE_TOP = Path("src/fpga/core/core_top.v")
DATA_JSON = Path("dist/Cores/RegionallyFamous.SwanSong/data.json")
QSF = Path("src/fpga/ap_core.qsf")
SAVE_INIT = Path("src/fpga/core/pocket_save_init.sv")
RTC_SAVE_LOADER = Path("src/fpga/core/apf_rtc_save_loader.sv")

EXPECTED_PAYLOAD_BYTES = {
    0x00: 0,
    0x01: 32_768,
    0x02: 32_768,
    0x03: 131_072,
    0x04: 262_144,
    0x05: 524_288,
    0x10: 128,
    0x20: 2_048,
    0x50: 1_024,
}
MAXIMUM_FILE_BYTES = 524_288 + 12
SAVE_PARAMETERS = 0x86

SV_LITERAL = (
    r"(?:(?:[0-9][0-9_]*)?'[sS]?[bBoOdDhH][0-9a-fA-F_]+|[0-9][0-9_]*)"
)


def strip_sv_comments(source: str) -> str:
    """Remove comments so a commented-out contract cannot satisfy a check."""

    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


def sv_int(token: str) -> int:
    compact = re.sub(r"[\s_]", "", token)
    if "'" not in compact:
        return int(compact, 10)

    _, suffix = compact.split("'", 1)
    if suffix[:1].lower() == "s":
        suffix = suffix[1:]
    if len(suffix) < 2:
        raise ValueError(f"malformed SystemVerilog integer {token!r}")
    base_name = suffix[0].lower()
    base = {"b": 2, "o": 8, "d": 10, "h": 16}.get(base_name)
    if base is None or re.search(r"[xXzZ?]", suffix[1:]):
        raise ValueError(f"non-constant SystemVerilog integer {token!r}")
    return int(suffix[1:], base)


def json_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError(f"not an integer: {value!r}")


def balanced_always_comb(source: str, required_token: str) -> str | None:
    """Return the always_comb body containing required_token, including nesting."""

    for match in re.finditer(r"\balways_comb\b", source):
        begin = re.search(r"\bbegin\b", source[match.end() :])
        if begin is None:
            continue
        body_start = match.end() + begin.end()
        depth = 1
        for token in re.finditer(r"\b(?:begin|end)\b", source[body_start:]):
            if token.group(0) == "begin":
                depth += 1
            else:
                depth -= 1
            if depth == 0:
                body = source[body_start : body_start + token.start()]
                if required_token in body:
                    return body
                break
    return None


def compact_expression(expression: str) -> str:
    return re.sub(r"\s+", "", expression)


def check_wonderswan(source: str) -> list[str]:
    errors: list[str] = []
    active = strip_sv_comments(source)

    if not re.search(
        r"\boutput\s+(?:logic|reg)\s*\[\s*19\s*:\s*0\s*\]"
        r"\s*save_size_bytes\b",
        active,
    ):
        errors.append(
            "wonderswan save_size_bytes must be a 20-bit procedural exact-byte output"
        )

    body = balanced_always_comb(active, "save_size_bytes")
    if body is None:
        errors.append("wonderswan exact-byte save_size_bytes mapping is missing")
    else:
        first_ramtype = re.search(r"\bif\s*\(\s*ramtype_mem\b", body)
        prefix = body[: first_ramtype.start()] if first_ramtype else body
        default_match = re.search(
            rf"\bsave_size_bytes\s*=\s*(?P<value>{SV_LITERAL})\s*;",
            prefix,
        )
        try:
            default = sv_int(default_match.group("value")) if default_match else None
        except ValueError:
            default = None

        assignment_pattern = re.compile(
            rf"\bif\s*\(\s*ramtype_mem\s*==\s*(?P<type>{SV_LITERAL})\s*\)"
            rf"\s*(?:begin\s*)?save_size_bytes\s*=\s*"
            rf"(?P<value>{SV_LITERAL})\s*;"
        )
        parsed: dict[int, int] = {}
        duplicates: set[int] = set()
        for match in assignment_pattern.finditer(body):
            try:
                ram_type = sv_int(match.group("type"))
                value = sv_int(match.group("value"))
            except ValueError:
                continue
            if ram_type in parsed:
                duplicates.add(ram_type)
            parsed[ram_type] = value

        for ram_type in sorted(duplicates):
            errors.append(f"ramtype 0x{ram_type:02X} has duplicate payload mappings")

        actual_payloads = {0x00: default, **parsed}
        for ram_type, expected in EXPECTED_PAYLOAD_BYTES.items():
            actual = actual_payloads.get(ram_type)
            if actual != expected:
                errors.append(
                    f"ramtype 0x{ram_type:02X} payload {actual!r} != {expected} bytes"
                )
        for ram_type in sorted(set(parsed) - set(EXPECTED_PAYLOAD_BYTES)):
            errors.append(
                f"unexpected ramtype 0x{ram_type:02X} persistence payload mapping"
            )

    if ".extra_data_addr(extra_data_addr)" not in compact_expression(active):
        errors.append(
            "wonderswan must obtain the exact-byte RTC boundary from its save loader"
        )

    rtc_assignments = re.findall(r"\bwire\s+has_rtc_mem\s*=\s*([^;]+);", active)
    if len(rtc_assignments) != 1:
        errors.append("wonderswan must have exactly one active has_rtc assignment")
    elif compact_expression(rtc_assignments[0]) != "lastdata[1][15:8]==8'h01":
        errors.append(
            "wonderswan has_rtc must require canonical ROM-footer RTC value 0x01"
        )

    compact = compact_expression(active)
    save_init_contract = {
        ".save_payload_write(sd_buff_wr&&!extra_data_addr)": (
            "save initializer must distinguish APF payload writes from RTC trailer writes"
        ),
        ".save_is_eeprom(save_is_eeprom_mem)": (
            "save initializer must use the explicit external-EEPROM type classifier"
        ),
        ".save_size_bytes(save_size_bytes)": (
            "save initializer must receive the exact selected payload capacity"
        ),
        ".eeprom_addr(clear_eeprom_write?clear_save_word_addr[9:0]:sd_buff_addr[10:1])": (
            "external EEPROM clear/load address mux must preserve all 1024 word addresses"
        ),
        ".eeprom_din(clear_eeprom_write?16'hFFFF:sd_buff_dout)": (
            "absent external EEPROM must initialize to native blank value 0xFFFF"
        ),
        ".eeprom_req(clear_eeprom_write||(save_is_eeprom_mem&&(sd_buff_rd||sd_buff_wr)&&~extra_data_addr))": (
            "external EEPROM request mux must include initialization and payload traffic only"
        ),
        ".eeprom_rnw(!clear_eeprom_write&&~sd_buff_wr)": (
            "external EEPROM initialization must select the write direction"
        ),
    }
    for expression, error in save_init_contract.items():
        if expression not in compact:
            errors.append(error)

    eeprom_types = re.search(r"\bwire\s+save_is_eeprom_mem\s*=\s*([^;]+);", active)
    expected_classifier = (
        "(ramtype_mem==8'h10)||(ramtype_mem==8'h20)||(ramtype_mem==8'h50)"
    )
    if eeprom_types is None or compact_expression(eeprom_types.group(1)) != expected_classifier:
        errors.append(
            "external-EEPROM classifier must be exactly ramtypes 0x10, 0x20, and 0x50"
        )

    return errors


def check_qsf(source: str) -> list[str]:
    assignments = re.findall(
        r"^\s*set_global_assignment\s+-name\s+SYSTEMVERILOG_FILE\s+(\S+)\s*$",
        source,
        flags=re.MULTILINE,
    )
    if assignments.count("core/pocket_save_init.sv") != 1:
        return ["Quartus project must compile pocket_save_init.sv exactly once"]
    return []


def check_rtc_save_loader(source: str) -> list[str]:
    active = strip_sv_comments(source)
    extra_match = re.search(
        r"\bassign\s+extra_data_addr\s*=\s*(?P<expression>[^;]+);", active
    )
    extra_expression = (
        compact_expression(extra_match.group("expression")) if extra_match else None
    )
    if extra_expression != "sd_buff_addr>={1'b0,save_size_bytes}":
        return [
            "RTC save loader boundary must compare sd_buff_addr directly to "
            "zero-extended exact-byte save_size_bytes"
        ]
    return []


def check_core_top(source: str) -> list[str]:
    errors: list[str] = []
    active = strip_sv_comments(source)

    if not re.search(
        r"\bwire\s*\[\s*19\s*:\s*0\s*\]\s*save_size_bytes\b", active
    ):
        errors.append("core_top save_size_bytes wire must preserve all 20 payload bits")
    if not re.search(
        r"\.save_size_bytes\s*\(\s*save_size_bytes\s*\)", active
    ):
        errors.append("core_top must connect the exact-byte save_size_bytes port")

    table_expressions = [
        expression
        for expression in re.findall(r"\bdatatable_data\s*<=\s*([^;]+);", active)
        if "save_size_bytes" in expression
    ]
    if len(table_expressions) != 1:
        errors.append(
            "core_top must publish exactly one dynamic save_size_bytes table formula"
        )
    else:
        expression = compact_expression(table_expressions[0])
        formula = re.fullmatch(
            rf"\{{(?P<upper>{SV_LITERAL}),save_size_bytes_74a\}}\+"
            rf"\(has_rtc_74a\?(?P<rtc>{SV_LITERAL}):"
            rf"(?P<none>{SV_LITERAL})\)",
            expression,
        )
        if formula is None:
            errors.append(
                "core_top nonvolatile table size must be exact payload plus a "
                "conditional 12-byte RTC trailer"
            )
        else:
            try:
                upper = sv_int(formula.group("upper"))
                rtc_bytes = sv_int(formula.group("rtc"))
                no_rtc_bytes = sv_int(formula.group("none"))
            except ValueError:
                upper = rtc_bytes = no_rtc_bytes = -1
            if upper != 0 or rtc_bytes != 12 or no_rtc_bytes != 0:
                errors.append(
                    "core_top RTC table contribution must be 12 bytes when has_rtc "
                    "is set and 0 otherwise"
                )

    table_addresses = [
        compact_expression(expression)
        for expression in re.findall(r"\bdatatable_addr\s*<=\s*([^;]+);", active)
    ]
    if not any(
        address == "2*3+1" or
        (re.fullmatch(SV_LITERAL, address) and sv_int(address) == 7)
        for address in table_addresses
    ):
        errors.append("core_top dynamic size must target Save data-slot index 3")

    return errors


def check_data_json(definition: object) -> list[str]:
    errors: list[str] = []
    try:
        data = definition["data"]  # type: ignore[index]
        slots = data["data_slots"]  # type: ignore[index]
    except (KeyError, TypeError):
        return ["data.json APF data_slots definition is missing"]

    if not isinstance(slots, list):
        return ["data.json data_slots must be an array"]

    saves: list[dict[str, object]] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        try:
            if json_int(slot.get("id")) == 11:
                saves.append(slot)
        except (TypeError, ValueError):
            continue
    if len(saves) != 1:
        return [f"data.json must contain exactly one Save slot with id 11, found {len(saves)}"]
    save = saves[0]

    if save.get("name") != "Save":
        errors.append("data.json slot 11 must be named Save")
    if save.get("required") is not False:
        errors.append("data.json Save slot must remain optional for absent-save startup")
    if save.get("nonvolatile") is not True:
        errors.append("data.json Save slot must be nonvolatile")
    if save.get("deferload") not in (None, False):
        errors.append("data.json Save slot must use automatic nonvolatile load/unload")
    if save.get("extensions") != ["sav"]:
        errors.append("data.json Save slot extension must be exactly sav")

    try:
        address = json_int(save.get("address"))
    except (TypeError, ValueError):
        address = None
    if address != 0x20000000:
        errors.append("data.json Save slot address must be 0x20000000")

    try:
        parameters = json_int(save.get("parameters"))
    except (TypeError, ValueError):
        parameters = None
    if parameters != SAVE_PARAMETERS:
        errors.append(
            "data.json Save parameters must be 0x86 "
            "(core-specific, cloned filename, writable, dynamic initialization, "
            "Chip32 restart)"
        )

    if "size_exact" in save:
        errors.append("data.json Save slot must omit size_exact for dynamic capacity")
    try:
        maximum = json_int(save.get("size_maximum"))
    except (TypeError, ValueError):
        maximum = None
    if maximum != MAXIMUM_FILE_BYTES:
        errors.append(
            f"data.json Save size_maximum {maximum!r} != {MAXIMUM_FILE_BYTES} bytes"
        )

    return errors


def verify_root(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        wonderswan = (root / WONDERSWAN).read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"cannot read {WONDERSWAN}: {error}")
    else:
        errors.extend(check_wonderswan(wonderswan))

    try:
        core_top = (root / CORE_TOP).read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"cannot read {CORE_TOP}: {error}")
    else:
        errors.extend(check_core_top(core_top))

    try:
        definition = json.loads((root / DATA_JSON).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"cannot load {DATA_JSON}: {error}")
    else:
        errors.extend(check_data_json(definition))

    try:
        qsf = (root / QSF).read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"cannot read {QSF}: {error}")
    else:
        errors.extend(check_qsf(qsf))

    if not (root / SAVE_INIT).is_file():
        errors.append(f"save initializer RTL is missing: {SAVE_INIT}")

    try:
        rtc_save_loader = (root / RTC_SAVE_LOADER).read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"cannot read {RTC_SAVE_LOADER}: {error}")
    else:
        errors.extend(check_rtc_save_loader(rtc_save_loader))
    return errors


def copy_contract_sources(destination: Path) -> None:
    for relative in (
        WONDERSWAN,
        CORE_TOP,
        DATA_JSON,
        QSF,
        SAVE_INIT,
        RTC_SAVE_LOADER,
    ):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def replace_regex_once(path: Path, pattern: str, replacement: str) -> None:
    source = path.read_text(encoding="utf-8")
    mutated, count = re.subn(pattern, replacement, source, count=1, flags=re.MULTILINE)
    if count != 1:
        raise AssertionError(f"mutation pattern matched {count} times in {path}: {pattern}")
    path.write_text(mutated, encoding="utf-8")


Mutation = Callable[[Path], None]


def source_mutation(relative: Path, pattern: str, replacement: str) -> Mutation:
    return lambda root: replace_regex_once(root / relative, pattern, replacement)


def json_mutation(change: Callable[[dict[str, object]], None]) -> Mutation:
    def mutate(root: Path) -> None:
        path = root / DATA_JSON
        definition = json.loads(path.read_text(encoding="utf-8"))
        slots = definition["data"]["data_slots"]
        save = next(slot for slot in slots if json_int(slot["id"]) == 11)
        change(save)
        path.write_text(json.dumps(definition), encoding="utf-8")

    return mutate


def must_reject(label: str, mutation: Mutation, expected_error: str) -> None:
    with tempfile.TemporaryDirectory(prefix="swan-song-pocket-nv-contract-") as name:
        root = Path(name)
        copy_contract_sources(root)
        mutation(root)
        errors = verify_root(root)
        if not errors:
            raise AssertionError(f"mutation {label!r} unexpectedly passed")
        if not any(expected_error in error for error in errors):
            detail = "\n  - ".join(errors)
            raise AssertionError(
                f"mutation {label!r} failed for the wrong reason; expected "
                f"{expected_error!r}:\n  - {detail}"
            )


def run_mutations() -> int:
    mutations: list[tuple[str, Mutation, str]] = []

    mutations.append(
        (
            "narrow-byte-width",
            source_mutation(
                WONDERSWAN,
                r"(output\s+(?:logic|reg)\s*)\[\s*19\s*:\s*0\s*\](\s*save_size_bytes)",
                r"\1[11:0]\2",
            ),
            "20-bit procedural exact-byte output",
        )
    )
    mutations.append(
        (
            "procedural-size-declared-wire",
            source_mutation(
                WONDERSWAN,
                r"output\s+logic(\s*\[\s*19\s*:\s*0\s*\]\s*save_size_bytes)",
                r"output wire\1",
            ),
            "20-bit procedural exact-byte output",
        )
    )

    for ram_type, expected in EXPECTED_PAYLOAD_BYTES.items():
        if ram_type == 0:
            mutation = source_mutation(
                WONDERSWAN,
                rf"^(\s*save_size_bytes\s*=\s*){SV_LITERAL}(\s*;)",
                r"\g<1>20'd1\g<2>",
            )
        else:
            mutation = source_mutation(
                WONDERSWAN,
                rf"(if\s*\(\s*ramtype_mem\s*==\s*8'h{ram_type:02X}\s*\)\s*"
                rf"save_size_bytes\s*=\s*){SV_LITERAL}(\s*;)",
                rf"\g<1>20'd{expected + 1}\g<2>",
            )
        mutations.append(
            (
                f"ramtype-{ram_type:02x}-payload",
                mutation,
                f"ramtype 0x{ram_type:02X} payload",
            )
        )

    mutations.extend(
        (
            (
                "wrong-eeprom-blank-value",
                source_mutation(
                    WONDERSWAN,
                    r"(clear_eeprom_write\s*\?\s*16'h)FFFF(\s*:\s*sd_buff_dout)",
                    r"\g<1>0000\g<2>",
                ),
                "native blank value 0xFFFF",
            ),
            (
                "rtc-write-suppresses-initialization",
                source_mutation(
                    WONDERSWAN,
                    r"(\.save_payload_write\s*\(\s*)sd_buff_wr\s*&&\s*!extra_data_addr(\s*\))",
                    r"\g<1>sd_buff_wr\g<2>",
                ),
                "distinguish APF payload writes",
            ),
            (
                "truncated-eeprom-clear-address",
                source_mutation(
                    WONDERSWAN,
                    r"(clear_eeprom_write\s*\?\s*clear_save_word_addr\s*\[)9(:\s*0\])",
                    r"\g<1>8\g<2>",
                ),
                "preserve all 1024 word addresses",
            ),
            (
                "wrong-eeprom-type-classifier",
                source_mutation(
                    WONDERSWAN,
                    r"(save_is_eeprom_mem\s*=(?:.|\n)*?ramtype_mem\s*==\s*8'h)50",
                    r"\g<1>51",
                ),
                "classifier must be exactly",
            ),
            (
                "initializer-missing-from-quartus",
                source_mutation(
                    QSF,
                    r"core/pocket_save_init\.sv",
                    "core/pocket_save_init_missing.sv",
                ),
                "Quartus project must compile",
            ),
            (
                "legacy-block-scaling",
                source_mutation(
                    RTC_SAVE_LOADER,
                    r"(assign\s+extra_data_addr\s*=\s*)sd_buff_addr\s*>=\s*"
                    r"\{1'b0,\s*save_size_bytes\}(\s*;)",
                    r"\1sd_buff_addr >= ({1'b0, save_size_bytes} * 512)\2",
                ),
                "compare sd_buff_addr directly to zero-extended exact-byte",
            ),
            (
                "forced-rtc",
                source_mutation(
                    WONDERSWAN,
                    r"(wire\s+has_rtc_mem\s*=\s*)lastdata\s*\[\s*1\s*\]\s*"
                    r"\[\s*15\s*:\s*8\s*\]\s*==\s*8'h01(\s*;)",
                    r"\g<1>1'b1\g<2>",
                ),
                "canonical ROM-footer RTC value",
            ),
            (
                "wrong-rtc-footer-value",
                source_mutation(
                    WONDERSWAN,
                    r"(wire\s+has_rtc_mem\s*=\s*lastdata\s*\[\s*1\s*\]\s*"
                    r"\[\s*15\s*:\s*8\s*\]\s*==\s*8'h)01(\s*;)",
                    r"\g<1>02\g<2>",
                ),
                "canonical ROM-footer RTC value",
            ),
            (
                "rtc-trailer-too-large",
                source_mutation(
                    CORE_TOP,
                    r"(save_size_bytes_74a\s*\}\s*\+\s*\(\s*"
                    r"has_rtc_74a\s*\?\s*32'd)12(\s*:\s*32'd0\s*\))",
                    r"\g<1>16\g<2>",
                ),
                "RTC table contribution must be 12 bytes",
            ),
            (
                "rtc-trailer-unconditional",
                source_mutation(
                    CORE_TOP,
                    r"(save_size_bytes_74a\s*\}\s*\+\s*\(\s*"
                    r"has_rtc_74a\s*\?\s*32'd12\s*:\s*32'd)0(\s*\))",
                    r"\g<1>12\g<2>",
                ),
                "and 0 otherwise",
            ),
            (
                "missing-size-maximum",
                json_mutation(lambda save: save.pop("size_maximum", None)),
                "size_maximum None != 524300 bytes",
            ),
            (
                "wrong-size-maximum",
                json_mutation(
                    lambda save: save.__setitem__("size_maximum", 524_288)
                ),
                "size_maximum 524288 != 524300 bytes",
            ),
            (
                "volatile-save",
                json_mutation(lambda save: save.__setitem__("nonvolatile", False)),
                "must be nonvolatile",
            ),
            (
                "fixed-size-save",
                json_mutation(lambda save: save.__setitem__("size_exact", 524_300)),
                "must omit size_exact",
            ),
            (
                "non-cloned-save-name",
                json_mutation(lambda save: save.__setitem__("parameters", "0x80")),
                "Save parameters must be 0x86",
            ),
            (
                "required-save",
                json_mutation(lambda save: save.__setitem__("required", True)),
                "must remain optional",
            ),
        )
    )

    for label, mutation, expected_error in mutations:
        must_reject(label, mutation, expected_error)
    return len(mutations)


def main() -> int:
    errors = verify_root(ROOT)
    if errors:
        print("FAIL Pocket nonvolatile size contract")
        for error in errors:
            print(f"- {error}")
        return 1

    mutation_count = run_mutations()
    payloads = ",".join(
        f"{ram_type:02X}={size}" for ram_type, size in EXPECTED_PAYLOAD_BYTES.items()
    )
    print(
        "PASS Pocket nonvolatile exact-byte contract "
        f"payloads={payloads} RTC=footer-01+12 size_maximum={MAXIMUM_FILE_BYTES} "
        f"mutations={mutation_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
