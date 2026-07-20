#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Regionally Famous contributors
"""Lint SWANFRAME-style WonderSwan C pattern and song data."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


def matching_paren(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("unclosed parenthesis")


def split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return parts


def lint(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    pattern_count = text.count("{ .row = {")
    row_count = 0

    for match in re.finditer(r"\[(\d+)\]\s*=\s*ROW\(", text):
        row_count += 1
        row = int(match.group(1))
        if not 0 <= row < 16:
            errors.append(f"row {row}: outside 0..15")
        opening = text.find("(", match.start())
        try:
            closing = matching_paren(text, opening)
        except ValueError as exc:
            errors.append(f"row {row}: {exc}")
            continue
        channels = split_top_level(text[opening + 1 : closing])
        if len(channels) != 4:
            errors.append(f"row {row}: ROW has {len(channels)} channels, expected 4")
            continue
        for channel, event in enumerate(channels, start=1):
            if event in {"N", "OFF"}:
                continue
            if not event.startswith("EV(") or not event.endswith(")"):
                errors.append(f"row {row} channel {channel}: malformed event {event!r}")
                continue
            fields = split_top_level(event[3:-1])
            if len(fields) != 4:
                errors.append(f"row {row} channel {channel}: EV needs four fields")
                continue
            note, instrument, volume_text, gate_text = fields
            note_match = re.fullmatch(r"[A-G](?:S)?\((\d+)\)", note)
            if note_match and not 2 <= int(note_match.group(1)) <= 7:
                errors.append(f"row {row} channel {channel}: note octave outside 2..7")
            try:
                volume = int(volume_text, 0)
                gate = int(gate_text, 0)
            except ValueError:
                errors.append(f"row {row} channel {channel}: volume/gate must be integers")
                continue
            if not 1 <= volume <= 15:
                errors.append(f"row {row} channel {channel}: volume {volume} outside 1..15")
            if not 1 <= gate <= 16:
                errors.append(f"row {row} channel {channel}: gate {gate} outside 1..16")
            if instrument.endswith(("_SNARE", "_HAT")) and channel != 4:
                errors.append(f"row {row} channel {channel}: noise instrument requires channel 4")
            if instrument.endswith("_SWEEP") and channel != 3:
                errors.append(f"row {row} channel {channel}: sweep instrument requires channel 3")

    song_re = re.compile(
        r'\{\s*\.title\s*=\s*"([^"]*)",\s*'
        r'\.subtitle\s*=\s*"([^"]*)",\s*'
        r'\.bpm\s*=\s*(\d+),\s*'
        r'\.order_length\s*=\s*(\d+),\s*'
        r'\.order\s*=\s*\{([^}]*)\}\s*\}',
        re.S,
    )
    songs = list(song_re.finditer(text))
    for number, match in enumerate(songs, start=1):
        title, subtitle = match.group(1), match.group(2)
        bpm, order_length = int(match.group(3)), int(match.group(4))
        try:
            order = [int(item.strip(), 0) for item in match.group(5).split(",") if item.strip()]
        except ValueError:
            errors.append(f"song {number} {title!r}: order must contain integer indices")
            continue
        if len(title) > 23:
            errors.append(f"song {number}: title is {len(title)} chars, maximum 23")
        if len(subtitle) > 26:
            errors.append(f"song {number}: subtitle is {len(subtitle)} chars, maximum 26")
        if not 40 <= bpm <= 300:
            errors.append(f"song {number} {title!r}: BPM {bpm} outside 40..300")
        if order_length != len(order):
            errors.append(
                f"song {number} {title!r}: order_length {order_length} != {len(order)} entries"
            )
        for pattern in order:
            if not 0 <= pattern < pattern_count:
                errors.append(
                    f"song {number} {title!r}: pattern {pattern} outside 0..{pattern_count - 1}"
                )

    if pattern_count == 0:
        errors.append("no pattern blocks found")
    if row_count == 0:
        errors.append("no ROW events found")
    if not songs:
        errors.append("no song metadata blocks found")

    print(f"{path}: {pattern_count} patterns, {row_count} populated rows, {len(songs)} songs")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("score", type=Path)
    args = parser.parse_args()
    errors = lint(args.score)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("score lint: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
