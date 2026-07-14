#!/usr/bin/env python3
"""Mutation-lock the evidence-backed timer IRQ comparator contract."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
GPU = ROOT / "src/fpga/core/rtl/gpu.vhd"


def assignment(source: str, signal: str) -> str:
    match = re.search(rf"^\s*{signal}\s*<=.*?;\s*$", source, re.MULTILINE)
    if not match:
        raise AssertionError(f"missing {signal} assignment")
    return match.group(0)


def validate(source: str) -> None:
    horizontal = assignment(source, "IRQ_HBlankTmr")
    vertical = assignment(source, "IRQ_VBlankTmr")

    for text, counter, enable in (
        (horizontal, "HTMR_CTR", r"TMR_CTRL\s*\(\s*0\s*\)"),
        (vertical, "VTMR_CTR", r"TMR_CTRL\s*\(\s*2\s*\)"),
    ):
        assert counter in text and re.search(r"=\s*1\b", text), text
        assert not re.search(enable, text), text

    assert "Timers&oldid=117" in source
    assert "ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2" in source
    assert "Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2" in source


def must_reject(source: str) -> None:
    try:
        validate(source)
    except AssertionError:
        return
    raise AssertionError("timer IRQ contract accepted an enable-gated mutant")


def main() -> None:
    source = GPU.read_text(encoding="utf-8")
    validate(source)

    must_reject(
        source.replace(
            "and unsigned(HTMR_CTR) = 1)",
            "and TMR_CTRL(0) = '1' and unsigned(HTMR_CTR) = 1)",
            1,
        )
    )
    must_reject(
        source.replace(
            "and unsigned(VTMR_CTR) = 1)",
            "and TMR_CTRL(2) = '1' and unsigned(VTMR_CTR) = 1)",
            1,
        )
    )
    print("PASS GPU HBlank/VBlank timer IRQ comparator contract and mutants")


if __name__ == "__main__":
    main()
