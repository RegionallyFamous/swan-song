#!/usr/bin/env python3
"""Mutation-lock the Pocket PLL boot-reset and loss-of-lock contracts."""

from __future__ import annotations

from collections.abc import Mapping
import base64
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CORE_TOP = "src/fpga/core/core_top.v"
PLL_QIP = "src/fpga/core/mf_pllbase/mf_pllbase_0002.qip"
PARENT_QIP = "src/fpga/core/mf_pllbase.qip"
PLL_WRAPPER = "src/fpga/core/mf_pllbase.v"
PRIMITIVE_WRAPPER = "src/fpga/core/mf_pllbase/mf_pllbase_0002.v"
PLL_SCOPE = "*mf_pllbase_0002*|altera_pll:altera_pll_i*|*"


class ContractError(ValueError):
    """The exact PLL reset/recovery contract was violated."""


def load_sources() -> dict[str, str]:
    return {
        relative: (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            CORE_TOP,
            PLL_QIP,
            PARENT_QIP,
            PLL_WRAPPER,
            PRIMITIVE_WRAPPER,
        )
    }


def _instance_body(source: str, module: str, instance: str) -> str:
    matches = re.findall(
        rf"\b{re.escape(module)}\s+{re.escape(instance)}\s*\((.*?)\)\s*;",
        source,
        re.DOTALL,
    )
    if len(matches) != 1:
        raise ContractError(
            f"expected exactly one {module} {instance} instance, found {len(matches)}"
        )
    return matches[0]


def _require_once(pattern: str, source: str, label: str) -> None:
    count = len(re.findall(pattern, source, re.MULTILINE | re.DOTALL))
    if count != 1:
        raise ContractError(f"{label}: expected exactly one match, found {count}")


def _decoded_component_parameters(source: str) -> dict[str, tuple[str, str]]:
    decoded: dict[str, tuple[str, str]] = {}
    for payload in re.findall(r'IP_COMPONENT_PARAMETER\s+"([^"]+)"', source):
        fields = payload.split("::")
        if len(fields) != 3:
            raise ContractError("malformed generated IP component parameter")
        try:
            name, value, label = (
                base64.b64decode(field, validate=True).decode("utf-8")
                for field in fields
            )
        except (ValueError, UnicodeDecodeError) as error:
            raise ContractError("invalid generated IP component parameter") from error
        if name in decoded:
            raise ContractError(f"duplicate generated IP component parameter {name}")
        decoded[name] = (value, label)
    return decoded


def _primitive_instance_body(source: str) -> str:
    matches = re.findall(r"\)\s+altera_pll_i\s*\((.*?)\)\s*;", source, re.DOTALL)
    if len(matches) != 1:
        raise ContractError(
            f"expected exactly one altera_pll_i primitive, found {len(matches)}"
        )
    return matches[0]


def _module_body(source: str, module: str) -> str:
    matches = re.findall(
        rf"\bmodule\s+{re.escape(module)}\s*\(.*?\)\s*;(.*?)\bendmodule\b",
        source,
        re.DOTALL,
    )
    if len(matches) != 1:
        raise ContractError(f"expected exactly one {module} module, found {len(matches)}")
    return matches[0]


def verify_contract(sources: Mapping[str, str]) -> None:
    missing = sorted(
        {CORE_TOP, PLL_QIP, PARENT_QIP, PLL_WRAPPER, PRIMITIVE_WRAPPER}
        - set(sources)
    )
    if missing:
        raise ContractError(f"missing PLL contract source(s): {missing!r}")

    core_top = sources[CORE_TOP]
    qip = sources[PLL_QIP]
    parent_qip = sources[PARENT_QIP]
    pll_wrapper = sources[PLL_WRAPPER]
    primitive_wrapper = sources[PRIMITIVE_WRAPPER]
    active_qip = "\n".join(
        line for line in qip.splitlines() if not line.lstrip().startswith("#")
    )
    assignments = re.findall(
        r'^\s*set_instance_assignment\s+-name\s+PLL_AUTO_RESET\s+(\S+)\s+'
        r'-to\s+"([^"]+)"\s*$',
        active_qip,
        re.MULTILINE,
    )
    if assignments != [("ON", PLL_SCOPE)]:
        raise ContractError(
            "PLL_AUTO_RESET must have one active ON assignment at the exact "
            f"primitive scope; found {assignments!r}"
        )

    _require_once(
        r'set_global_assignment\s+-library\s+"mf_pllbase"\s+'
        r'-name\s+QIP_FILE\s+\[file join \$::quartus\(qip_path\)\s+'
        r'"mf_pllbase/mf_pllbase_0002[.]qip"\]',
        parent_qip,
        "parent QIP inclusion of the primitive assignment file",
    )
    parameters = _decoded_component_parameters(parent_qip)
    if parameters.get("gui_pll_auto_reset") != ("On", "PLL Auto Reset"):
        raise ContractError("generated parent QIP reports PLL Auto Reset other than On")
    try:
        names = parameters["gui_parameter_list"][0].split(",")
        values = parameters["gui_parameter_values"][0].split(",")
    except KeyError as error:
        raise ContractError("generated parent QIP lacks the parameter list/value pair") from error
    if len(names) != len(values) or names[-1] != "PLL Auto Reset" or values[-1] != "true":
        raise ContractError("generated parent QIP parameter vector does not end in auto reset=true")

    _require_once(
        r'<generic\s+name="gui_pll_auto_reset"\s+value="On"\s*/>',
        pll_wrapper,
        "generated wrapper auto-reset retrieval metadata",
    )
    if re.search(r'gui_pll_auto_reset"\s+value="Off"', pll_wrapper):
        raise ContractError("generated wrapper retains stale auto-reset Off metadata")
    generated = _instance_body(pll_wrapper, "mf_pllbase_0002", "mf_pllbase_inst")
    for connection in (
        r"[.]refclk\s*\(\s*refclk\s*\)",
        r"[.]rst\s*\(\s*rst\s*\)",
        r"[.]outclk_0\s*\(\s*outclk_0\s*\)",
        r"[.]outclk_1\s*\(\s*outclk_1\s*\)",
        r"[.]outclk_2\s*\(\s*outclk_2\s*\)",
        r"[.]outclk_3\s*\(\s*outclk_3\s*\)",
        r"[.]locked\s*\(\s*locked\s*\)",
    ):
        _require_once(connection, generated, f"generated PLL wrapper {connection}")
    primitive = _primitive_instance_body(primitive_wrapper)
    for connection in (
        r"[.]rst\s*\(\s*rst\s*\)",
        r"[.]outclk\s*\(\s*\{outclk_3,\s*outclk_2,\s*outclk_1,\s*outclk_0\}\s*\)",
        r"[.]locked\s*\(\s*locked\s*\)",
        r"[.]refclk\s*\(\s*refclk\s*\)",
    ):
        _require_once(connection, primitive, f"primitive PLL wrapper {connection}")

    boot_reset = _module_body(core_top, "apf_pll_boot_reset")
    for statement in (
        r"reg\s+\[3:0\]\s+elapsed_cycles\s*=\s*4'd0\s*;",
        r"always\s*@\s*\(\s*posedge\s+clk\s*\)",
        r"if\s*\(\s*!elapsed_cycles\[3\]\s*\)",
        r"elapsed_cycles\s*<=\s*elapsed_cycles\s*\+\s*4'd1\s*;",
        r"assign\s+reset\s*=\s*!elapsed_cycles\[3\]\s*;",
    ):
        _require_once(statement, boot_reset, f"boot-only reset statement {statement}")
    for forbidden in ("reset_n", "pll_core_locked", "host_reset"):
        if re.search(rf"\b{re.escape(forbidden)}\b", boot_reset):
            raise ContractError(
                f"boot-only PLL reset must not depend on {forbidden}"
            )

    boot_reset_instance = _instance_body(
        core_top, "apf_pll_boot_reset", "pll_boot_reset_generator"
    )
    for connection in (
        r"\.clk\s*\(\s*clk_74a\s*\)",
        r"\.reset\s*\(\s*pll_core_boot_reset\s*\)",
    ):
        _require_once(
            connection,
            boot_reset_instance,
            f"boot-only reset connection {connection}",
        )

    pll = _instance_body(core_top, "mf_pllbase", "mp1")
    required_connections = (
        r"\.refclk\s*\(\s*clk_74a\s*\)",
        r"\.rst\s*\(\s*pll_core_boot_reset\s*\)",
        r"\.outclk_0\s*\(\s*clk_mem_110_592\s*\)",
        r"\.outclk_1\s*\(\s*clk_sys_36_864\s*\)",
        r"\.outclk_2\s*\(\s*clk_vid_3_75\s*\)",
        r"\.outclk_3\s*\(\s*clk_vid_3_75_90deg\s*\)",
        r"\.locked\s*\(\s*pll_core_locked\s*\)",
    )
    for connection in required_connections:
        _require_once(connection, pll, f"PLL connection {connection}")
    if len(re.findall(r"\.rst\s*\(", pll)) != 1:
        raise ContractError("PLL must expose exactly one reset connection")

    # The lock signal asynchronously asserts both readiness resets. These are
    # deliberately distinct from Pocket's host reset protocol.
    for instance, clock, output in (
        ("pll_ready_bridge", "clk_74a", "pll_core_ready_74a"),
        ("pll_ready_memory", "clk_mem_110_592", "pll_core_ready_mem"),
    ):
        body = _instance_body(core_top, "apf_reset_sync", instance)
        for connection in (
            rf"\.clk\s*\(\s*{re.escape(clock)}\s*\)",
            r"\.reset_n_async\s*\(\s*pll_core_locked\s*\)",
            rf"\.reset_n_sync\s*\(\s*{re.escape(output)}\s*\)",
        ):
            _require_once(connection, body, f"{instance} connection {connection}")


def must_reject(
    sources: Mapping[str, str],
    relative: str,
    old: str,
    new: str,
    label: str,
) -> None:
    if old not in sources[relative]:
        raise AssertionError(f"stale mutation {label!r}: {old!r} not found")
    mutated = dict(sources)
    mutated[relative] = mutated[relative].replace(old, new, 1)
    try:
        verify_contract(mutated)
    except ContractError:
        return
    raise AssertionError(f"invalid PLL mutation passed: {label}")


def main() -> None:
    sources = load_sources()
    verify_contract(sources)
    vector_line = next(
        line
        for line in sources[PARENT_QIP].splitlines()
        if "Z3VpX3BhcmFtZXRlcl92YWx1ZXM=" in line
    )
    vector_payload = re.search(r'"([^"]+)"$', vector_line)
    if vector_payload is None:
        raise AssertionError("generated parameter-vector mutation fixture is stale")
    fields = vector_payload.group(1).split("::")
    vector_value = base64.b64decode(fields[1], validate=True).decode("utf-8")
    if not vector_value.endswith(",true"):
        raise AssertionError("generated auto-reset parameter vector is not true")
    fields[1] = base64.b64encode((vector_value[:-4] + "false").encode()).decode()
    stale_vector_line = vector_line.replace(
        vector_payload.group(1), "::".join(fields), 1
    )

    mutations = (
        (PLL_QIP, "PLL_AUTO_RESET ON", "PLL_AUTO_RESET OFF", "disable auto reset"),
        (
            CORE_TOP,
            ".rst   (pll_core_boot_reset)",
            ".rst   (1'b0)",
            "disconnect boot-only reset",
        ),
        (
            CORE_TOP,
            ".rst   (pll_core_boot_reset)",
            ".rst   (~pll_core_locked)",
            "self-latching reset",
        ),
        (
            CORE_TOP,
            "reg [3:0] elapsed_cycles = 4'd0;",
            "reg [3:0] elapsed_cycles = 4'd1;",
            "shorten boot reset",
        ),
        (
            CORE_TOP,
            "if (!elapsed_cycles[3])",
            "if (!reset_n)",
            "couple boot reset to host reset",
        ),
        (
            CORE_TOP,
            ".clk  (clk_74a)",
            ".clk  (clk_mem_110_592)",
            "detach boot reset from raw reference clock",
        ),
        (
            CORE_TOP,
            ".locked(pll_core_locked)",
            ".locked()",
            "disconnect lock output",
        ),
        (
            PLL_QIP,
            f'PLL_AUTO_RESET ON -to "{PLL_SCOPE}"',
            'PLL_AUTO_RESET ON -to "*mf_pllbase_0002*|altera_pll:wrong_instance*|*"',
            "mis-scope auto reset",
        ),
        (
            CORE_TOP,
            ".reset_n_async(pll_core_locked)",
            ".reset_n_async(reset_n)",
            "detach readiness synchronizer",
        ),
        (
            PARENT_QIP,
            "Z3VpX3BsbF9hdXRvX3Jlc2V0::T24=::UExMIEF1dG8gUmVzZXQ=",
            "Z3VpX3BsbF9hdXRvX3Jlc2V0::T2Zm::UExMIEF1dG8gUmVzZXQ=",
            "stale generated parent QIP metadata",
        ),
        (
            PLL_WRAPPER,
            'gui_pll_auto_reset" value="On"',
            'gui_pll_auto_reset" value="Off"',
            "stale generated wrapper metadata",
        ),
        (
            PARENT_QIP,
            '"mf_pllbase/mf_pllbase_0002.qip"',
            '"mf_pllbase/missing_auto_reset_assignment.qip"',
            "omit primitive assignment QIP",
        ),
        (
            PLL_WRAPPER,
            ".rst      (rst)",
            ".rst      (1'b0)",
            "generated wrapper drops reset",
        ),
        (
            PRIMITIVE_WRAPPER,
            ".rst\t(rst)",
            ".rst\t(1'b0)",
            "primitive wrapper drops reset",
        ),
        (
            PARENT_QIP,
            vector_line,
            stale_vector_line,
            "stale generated auto-reset parameter vector",
        ),
    )
    for relative, old, new, label in mutations:
        must_reject(sources, relative, old, new, label)
    print(
        "PASS PLL boot-reset and loss-of-lock recovery contract "
        f"mutations={len(mutations)}"
    )


if __name__ == "__main__":
    main()
