#!/usr/bin/env python3
"""Lock the official 32-bit PAD path and fail-closed gamepad classification."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def active(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


def compact(source: str) -> str:
    return re.sub(r"\s+", "", active(source))


def verify_contract(sources: dict[str, str]) -> None:
    pad = compact(sources["pad"])
    apf_top = compact(sources["apf_top"])
    core_top = compact(sources["core_top"])
    gamepad_filter = compact(sources["filter"])
    qsf = sources["qsf"]
    regression = sources["regression"]

    for player in range(1, 5):
        if f"outputreg[31:0]cont{player}_key" not in pad:
            raise ValueError(f"PAD player {player} key word is not 32-bit")
        if f"wire[31:0]cont{player}_key;" not in apf_top:
            raise ValueError(f"APF top player {player} key wire is not 32-bit")
        if f"inputwire[31:0]cont{player}_key" not in core_top:
            raise ValueError(f"core top player {player} key port is not 32-bit")

    for word_index, player in ((0, 1), (3, 2), (6, 3), (9, 4)):
        expected = (
            "0:begincont1_key<=rx_word;cont1_key_updated<=1;"
            if player == 1
            else f"{word_index}:cont{player}_key<=rx_word;"
        )
        if expected not in pad:
            raise ValueError(
                f"PAD player {player} does not capture the complete rx_word"
            )

    # ST_RESET plus the explicit timeout/reset overrides each invalidate raw
    # state.  This protects even downstream consumers that do not use P1.
    for signal in (
        *(f"cont{player}_key" for player in range(1, 5)),
        *(f"cont{player}_joy" for player in range(1, 5)),
        *(f"cont{player}_trig" for player in range(1, 5)),
    ):
        if pad.count(f"{signal}<=0;") < 3:
            raise ValueError(f"PAD reset/timeout does not invalidate {signal}")

    for fragment in (
        "wirevalid_gamepad=key_word[31:28]==TYPE_POCKET||"
        "key_word[31:28]==TYPE_DOCK_DIGITAL||"
        "key_word[31:28]==TYPE_DOCK_ANALOG;",
        "TYPE_POCKET,TYPE_DOCK_DIGITAL,TYPE_DOCK_ANALOG:begin"
        "buttons<=key_word[15:0];input_blocked<=1'b0;end",
        "elseif(os_focus_lost)beginbuttons<=16'd0;",
        "if(key_word_updated&&neutral_gamepad)begin",
    ):
        if fragment not in gamepad_filter:
            raise ValueError(
                "gamepad filter must accept only APF types 1-3 and guard PocketOS focus"
            )

    for fragment in (
        ".clk(clk_74a)",
        ".reset_n(reset_n)",
        ".os_focus_lost(osnotify_inmenu)",
        ".key_word_updated(cont1_key_updated)",
        ".key_word(cont1_key)",
        ".buttons(cont1_gamepad_key_74a)",
        ".input_blocked(physical_input_blocked_74a)",
    ):
        if fragment not in core_top:
            raise ValueError(f"gamepad filter integration is missing {fragment}")
    for fragment in (
        "apf_input_blocked_cdcinput_state_system_cdc(",
        ".buttons_source(cont1_gamepad_key_74a)",
        ".input_blocked_source(physical_input_blocked_74a)",
        ".buttons_destination(cont1_key_s)",
        ".input_blocked_destination(physical_input_blocked_sys_s)",
    ):
        if fragment not in core_top:
            raise ValueError(f"atomic system input CDC is missing {fragment}")
    if ".buttons_source(cont1_key[15:0])" in core_top:
        raise ValueError("raw PAD key word bypasses the gamepad type filter")

    if "SYSTEMVERILOG_FILE core/apf_gamepad_filter.sv" not in qsf:
        raise ValueError("Quartus project omits apf_gamepad_filter.sv")
    if '"$ROOT/sim/rtl/run_apf_gamepad_filter_tb.sh"' not in regression:
        raise ValueError("regression omits the APF PAD RTL bench")


def main() -> None:
    paths = {
        "pad": ROOT / "src/fpga/apf/io_pad_controller.v",
        "apf_top": ROOT / "src/fpga/apf/apf_top.v",
        "core_top": ROOT / "src/fpga/core/core_top.v",
        "filter": ROOT / "src/fpga/core/apf_gamepad_filter.sv",
        "qsf": ROOT / "src/fpga/ap_core.qsf",
        "regression": ROOT / "scripts/regression.sh",
    }
    sources = {name: path.read_text() for name, path in paths.items()}
    verify_contract(sources)

    mutations = (
        ("pad", "output  reg     [31:0]  cont1_key", "output  reg     [15:0]  cont1_key"),
        ("pad", "cont1_key <= rx_word;", "cont1_key <= rx_word[15:0];"),
        ("pad", "cont4_trig <= 0;", "cont4_trig <= cont4_trig;"),
        ("apf_top", "wire    [31:0]  cont4_key", "wire    [15:0]  cont4_key"),
        ("core_top", "input wire [31:0] cont2_key", "input wire [15:0] cont2_key"),
        (
            "core_top",
            ".buttons_source(cont1_gamepad_key_74a)",
            ".buttons_source(cont1_key[15:0])",
        ),
        (
            "filter",
            "TYPE_DOCK_ANALOG: begin",
            "TYPE_DOCK_ANALOG, 4'h4: begin",
        ),
        ("filter", "else if (os_focus_lost)", "else if (1'b0)"),
        ("qsf", "core/apf_gamepad_filter.sv", "core/missing_gamepad_filter.sv"),
        (
            "regression",
            '"$ROOT/sim/rtl/run_apf_gamepad_filter_tb.sh"',
            '"$ROOT/sim/rtl/run_missing_gamepad_filter_tb.sh"',
        ),
    )

    rejected = 0
    for source_name, old, new in mutations:
        if old not in sources[source_name]:
            raise RuntimeError(f"mutation anchor missing from {source_name}: {old!r}")
        mutated = dict(sources)
        mutated[source_name] = mutated[source_name].replace(old, new, 1)
        try:
            verify_contract(mutated)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError(
                f"PAD contract accepted mutation in {source_name}: {old!r}"
            )

    print(
        "PASS Pocket PAD 32-bit/type-filter source contract "
        f"({rejected} adversarial mutations rejected)"
    )


if __name__ == "__main__":
    main()
