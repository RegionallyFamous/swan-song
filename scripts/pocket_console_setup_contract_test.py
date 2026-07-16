#!/usr/bin/env python3
"""Lock the player-facing removal of the legacy Console Setup action."""

from __future__ import annotations

import copy
import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parent.parent
INTERACT = ROOT / "dist/Cores/RegionallyFamous.SwanSong/interact.json"


def number(value: int | str) -> int:
    return int(value, 0) if isinstance(value, str) else value


def verify_contract(interact: dict) -> None:
    variables = interact["interact"]["variables"]
    if any(number(item["id"]) == 1 for item in variables):
        raise ValueError("legacy Console Setup ID 1 must not be player-visible")
    if any(item["name"].casefold() == "console setup" for item in variables):
        raise ValueError("legacy Console Setup label must not be player-visible")
    if any(number(item.get("address", -1)) == 0x54 for item in variables):
        raise ValueError("legacy Console Setup bridge action must not be player-visible")

    inert_headings = {
        number(item["id"]): item
        for item in variables
        if number(item["id"]) in (40, 80)
    }
    if inert_headings != {
        40: {
            "name": "Video",
            "id": 40,
            "type": "action",
            "enabled": False,
            "address": "0x58",
            "value": 0,
        },
        80: {
            "name": "Sound",
            "id": 80,
            "type": "action",
            "enabled": False,
            "address": "0x5C",
            "value": 0,
        },
    }:
        raise ValueError("disabled Interact heading contract changed")


def main() -> None:
    interact = json.loads(INTERACT.read_text(encoding="utf-8"))
    verify_contract(interact)

    forbidden = (
        {"name": "Console Setup", "id": 1, "type": "action", "enabled": True,
         "address": "0x54", "value": 1},
        {"name": "Setup", "id": 99, "type": "action", "enabled": True,
         "address": "0x54", "value": 1},
    )
    rejected = 0
    for item in forbidden:
        changed = copy.deepcopy(interact)
        changed["interact"]["variables"].append(item)
        try:
            verify_contract(changed)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError("removed Console Setup surface accepted a mutation")

    print(
        "PASS legacy Console Setup is absent from Interact "
        f"({rejected} adversarial mutations rejected)"
    )


if __name__ == "__main__":
    main()
