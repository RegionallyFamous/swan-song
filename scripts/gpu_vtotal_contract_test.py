#!/usr/bin/env python3
"""Mutation-lock programmable LCD final-line timing and beam threshold."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
GPU = ROOT / "src/fpga/core/rtl/gpu.vhd"
BEAM = ROOT / "scripts/beam_race_safety.py"
SPRITES = ROOT / "src/fpga/core/rtl/sprites.vhd"


def assignment(source: str, signal: str) -> str:
    match = re.search(rf"^\s*{signal}\s*<=.*?;\s*$", source, re.MULTILINE)
    if not match:
        raise AssertionError(f"missing {signal} assignment")
    return match.group(0)


def validate_gpu(source: str) -> None:
    assert re.search(
        r"unsigned\s*\(\s*LINE_CUR\s*\)\s*>=\s*unsigned\s*\(\s*LCD_VTOTAL\s*\)",
        source,
    )
    assert "LINE_CUR <= lineNext;" in source
    assert "lineEntering144 <= '1' when lineNext = x\"90\" else '0';" in source

    line_irq = assignment(source, "IRQ_LineComp")
    vblank = assignment(source, "IRQ_VBlank")
    vblank_timer = assignment(source, "IRQ_VBlankTmr")
    assert "lineNext = LINE_CMP" in line_irq
    assert "lineEntering144 = '1'" in vblank
    assert "lineEntering144 = '1'" in vblank_timer

    # Combinational request, sequential arm, and vertical timer update all use
    # the same actual-entry predicate; losing any one recreates final143 bugs.
    assert source.count("lineEntering144 = '1'") >= 5
    assert "xCount = 32 and spritePrefetchActive = '1'" in source
    assert "unsigned(LINE_CUR) /= 144 and unsigned(lineNext) < 144" in source
    assert "spriteFetchLineY  <= spritePrefetchLine;" in source

    # Line144 row0 is decoded from each newly completed odd DMA response. The
    # current+pending tile stream drains before a deferred, beam-aligned start;
    # it must never fall back to scanning a partial spriteRAM table.
    assert "dmaDescriptor := RAM_dataread & spriteDMAData;" in source
    assert "spriteRow0CurrentValid" in source
    assert "spriteRow0PendingValid" in source
    assert "spriteRow0TileOutstanding" in source
    assert "spriteDMAResponseIndex = x\"FF\"" in source
    assert "spriteRow0DMAComplete = '1'" in source
    assert "spritesLoadNext = '0'" in source
    assert "spriteStartLine <= spriteRow0Ready" in source
    assert "spriteStartX <= std_logic_vector(xCount)" in source

    assert re.search(
        r"outputLineActive\s*<=\s*'1'\s+when\s+unsigned\s*\(\s*LINE_CUR\s*\)\s*>\s*0\s+and\s+unsigned\s*\(\s*LINE_CUR\s*\)\s*<=\s*144",
        source,
    )
    assert re.search(
        r"renderLineActive\s*<=\s*'1'\s+when\s+unsigned\s*\(\s*LINE_CUR\s*\)\s*<\s*144",
        source,
    )
    assert "lineY <= LINE_CUR;" in source
    assert "renderLineBuffer(bufferIndex) <= renderedPixel;" in source
    assert "pixel_out_data <= renderLineBuffer(bufferIndex);" in source
    assert "renderBufferValid = '1'" in source
    assert "renderBufferRow = outputLineY" in source
    assert "renderLineStarted = '1'" in source
    assert "renderBufferValid <= '0';" in source
    assert "lineWillWrap" not in source
    assert not re.search(
        r"unsigned\s*\(\s*LINE_CUR\s*\)\s*(?:=|<|<=|>=|>)\s*15[78]\b",
        source,
    )


def validate_beam(source: str) -> None:
    assert "def programmable_final_line_counterexample(final_line: int = 143)" in source
    assert "if final_line >= HEIGHT:" in source
    assert re.search(r"^\s*first_stale_row\s*=\s*final_line\s*$", source, re.MULTILINE)
    assert "if final_line < HEIGHT:" in source


def validate_sprites(source: str) -> None:
    assert "startX         : in  std_logic_vector(7 downto 0)" in source
    assert "pixelCount     <= to_integer(unsigned(startX));" in source
    assert "posX           <= unsigned(startX) - 15;" in source
    assert "wxCheck        <= unsigned(startX) - 14;" in source


def must_reject_gpu(source: str, label: str) -> None:
    try:
        validate_gpu(source)
    except AssertionError:
        return
    raise AssertionError(f"GPU vtotal contract accepted mutant: {label}")


def must_reject_beam(source: str, label: str) -> None:
    try:
        validate_beam(source)
    except AssertionError:
        return
    raise AssertionError(f"beam threshold contract accepted mutant: {label}")


def main() -> None:
    gpu = GPU.read_text(encoding="utf-8")
    beam = BEAM.read_text(encoding="utf-8")
    sprites = SPRITES.read_text(encoding="utf-8")
    validate_gpu(gpu)
    validate_beam(beam)
    validate_sprites(sprites)

    for old, new, label in (
        (">= unsigned(LCD_VTOTAL)", "= unsigned(LCD_VTOTAL)", "missed live lower"),
        ("lineNext = LINE_CMP", "unsigned(LINE_CUR) + 1 = unsigned(LINE_CMP)", "hard wrap compare"),
        ("lineEntering144 = '1'", "unsigned(LINE_CUR) = 143", "ungated short-frame event"),
        ("unsigned(lineNext) < 144", "unsigned(LINE_CUR) = 158", "terminal-only sprite prefetch"),
        ("unsigned(LINE_CUR) /= 144", "unsigned(LINE_CUR) = 144", "partial-OAM ordinary scan"),
        ("spriteFetchLineY  <= spritePrefetchLine;", "spriteFetchLineY  <= LINE_CUR;", "same-line sprite fetch"),
        ("dmaDescriptor := RAM_dataread & spriteDMAData;", "dmaDescriptor := spriteRAM(dmaDescriptorIndex);", "stale row0 descriptor"),
        ("spriteDMAResponseIndex = x\"FF\"", "spriteDMAResponseIndex = x\"FD\"", "early row0 DMA complete"),
        ("spritesLoadNext = '0'", "spritesLoadNext = '1'", "same-edge Next snapshot"),
        ("unsigned(LINE_CUR) > 0", "unsigned(LINE_CUR) >= 0", "line0 publication"),
        ("unsigned(LINE_CUR) < 144", "unsigned(LINE_CUR) > 0 and unsigned(LINE_CUR) <= 144", "shifted render phase"),
        ("renderBufferValid = '1'", "renderBufferValid = '0'", "invalid row publication"),
        ("renderBufferRow = outputLineY", "renderBufferRow /= outputLineY", "stale row publication"),
    ):
        assert old in gpu, label
        must_reject_gpu(gpu.replace(old, new, 1), label)

    for old, new, label in (
        ("pixelCount     <= to_integer(unsigned(startX));", "pixelCount     <= 0;", "late-start pixel count"),
        ("posX           <= unsigned(startX) - 15;", "posX           <= to_unsigned(0, 8) - 15;", "late-start sprite position"),
        ("wxCheck        <= unsigned(startX) - 14;", "wxCheck        <= to_unsigned(0, 8) - 14;", "late-start window position"),
    ):
        assert old in sprites, label
        try:
            validate_sprites(sprites.replace(old, new, 1))
        except AssertionError:
            continue
        raise AssertionError(f"sprite startX contract accepted mutant: {label}")

    for old, new, label in (
        ("if final_line >= HEIGHT:", "if final_line >= HEIGHT - 1:", "counterexample final143 accepted"),
        ("if final_line < HEIGHT:", "if final_line < HEIGHT - 1:", "opportunity final143 accepted"),
        ("first_stale_row = final_line", "first_stale_row = final_line + 1", "stale row off by one"),
    ):
        assert old in beam, label
        must_reject_beam(beam.replace(old, new, 1), label)

    print("PASS GPU programmable-vtotal and beam full-frame threshold contracts and mutants")


if __name__ == "__main__":
    main()
