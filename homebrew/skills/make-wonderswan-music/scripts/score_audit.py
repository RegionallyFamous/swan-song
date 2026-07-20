#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Regionally Famous contributors
"""Report release-facing structure metrics for SWANFRAME-style C scores."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re


CHANNELS = 4
ROWS_PER_BAR = 16


def matching(text: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"unclosed {opening}")


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


@dataclass
class PatternStats:
    events: list[int]
    instruments: list[set[str]]
    event_rows: list[list[int]]


@dataclass
class Song:
    title: str
    bpm: int
    order: list[int]


def parse_patterns(text: str) -> list[PatternStats]:
    patterns: list[PatternStats] = []
    cursor = 0
    marker = "{ .row = {"
    while True:
        start = text.find(marker, cursor)
        if start < 0:
            break
        row_open = text.find("{", start + len("{ .row = "))
        row_close = matching(text, row_open, "{", "}")
        block = text[row_open + 1 : row_close]
        stats = PatternStats(
            events=[0] * CHANNELS,
            instruments=[set() for _ in range(CHANNELS)],
            event_rows=[[] for _ in range(CHANNELS)],
        )
        for row_match in re.finditer(r"\[(\d+)\]\s*=\s*ROW\(", block):
            row = int(row_match.group(1))
            opening = block.find("(", row_match.start())
            closing = matching(block, opening, "(", ")")
            channels = split_top_level(block[opening + 1 : closing])
            if len(channels) != CHANNELS:
                continue
            for channel, event in enumerate(channels):
                if not event.startswith("EV("):
                    continue
                fields = split_top_level(event[3:-1])
                if len(fields) != 4:
                    continue
                stats.events[channel] += 1
                stats.instruments[channel].add(fields[1])
                stats.event_rows[channel].append(row)
        patterns.append(stats)
        cursor = row_close + 1
    return patterns


def parse_songs(text: str) -> list[Song]:
    song_re = re.compile(
        r'\{\s*\.title\s*=\s*"([^"]*)",\s*'
        r'\.subtitle\s*=\s*"[^"]*",\s*'
        r'\.bpm\s*=\s*(\d+),\s*'
        r'\.order_length\s*=\s*(\d+),\s*'
        r'\.order\s*=\s*\{([^}]*)\}\s*\}',
        re.S,
    )
    songs: list[Song] = []
    for match in song_re.finditer(text):
        order = [int(item.strip(), 0) for item in match.group(4).split(",") if item.strip()]
        songs.append(Song(match.group(1), int(match.group(2)), order))
    return songs


def form(order: list[int]) -> str:
    names: dict[int, str] = {}
    labels: list[str] = []
    for pattern in order:
        if pattern not in names:
            index = len(names)
            names[pattern] = chr(ord("A") + index) if index < 26 else f"P{index + 1}"
        labels.append(names[pattern])
    return " ".join(labels)


def audit(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    patterns = parse_patterns(text)
    songs = parse_songs(text)
    print(f"{path}: {len(patterns)} patterns, {len(songs)} songs")

    forms: list[str] = []
    durations: list[float] = []
    for song in songs:
        bars = len(song.order)
        duration = bars * 240.0 / song.bpm
        durations.append(duration)
        song_form = form(song.order)
        forms.append(song_form)
        unique = len(set(song.order))
        events = [0] * CHANNELS
        even_percussion = 0
        percussion_events = 0
        instruments = [set() for _ in range(CHANNELS)]
        for pattern_index in song.order:
            if not 0 <= pattern_index < len(patterns):
                continue
            pattern = patterns[pattern_index]
            for channel in range(CHANNELS):
                events[channel] += pattern.events[channel]
                instruments[channel].update(pattern.instruments[channel])
            percussion_events += len(pattern.event_rows[3])
            even_percussion += sum(row % 2 == 0 for row in pattern.event_rows[3])
        density = [event / (bars * ROWS_PER_BAR) if bars else 0 for event in events]
        even_share = even_percussion / percussion_events if percussion_events else 0
        print(
            f"- {song.title}: {song.bpm} BPM, {bars} bars, {duration:.1f}s, "
            f"{unique} unique patterns, form {song_form}"
        )
        print(
            "  trigger density ch1-ch4: "
            + ", ".join(f"{value:.0%}" for value in density)
            + f"; ch4 even-row share {even_share:.0%}"
        )
        print(
            "  instrument variety ch1-ch4: "
            + ", ".join(str(len(values)) for values in instruments)
        )
        if duration < 30:
            print("  advisory: short-form microloop; consider a longer form for standalone listening")
        if unique <= 3:
            print("  advisory: limited unique pattern material; vary phrasing or arrangement by section")

    if songs and len(set(forms)) == 1:
        print(f"catalog advisory: every song uses the same normalized form ({forms[0]})")
    if durations:
        print(
            f"catalog duration range: {min(durations):.1f}-{max(durations):.1f}s "
            f"(mean {sum(durations) / len(durations):.1f}s)"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("score", type=Path)
    args = parser.parse_args()
    audit(args.score)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
