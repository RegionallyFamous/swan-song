#!/usr/bin/env python3
"""Lock the documented Pocket launcher/Library boundary to shipped metadata."""

from __future__ import annotations

import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
CORE_DIR = DIST / "Cores/agg23.WonderSwan"
AUDIT = ROOT / "POCKET_LAUNCHER_LIBRARY.md"


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def all_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).casefold())
            keys.update(all_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(all_keys(child))
    return keys


class PocketLauncherLibraryContractTest(unittest.TestCase):
    def test_supported_openfpga_package_has_no_guessed_os_payload(self) -> None:
        self.assertTrue(
            {"Assets", "Cores", "Platforms"}.issubset(
                {path.name for path in DIST.iterdir() if path.is_dir()}
            )
        )
        self.assertFalse(any(path.name.casefold() == "system" for path in DIST.rglob("*")))

        definitions = [load_json(path) for path in CORE_DIR.glob("*.json")]
        definitions.append(load_json(DIST / "Platforms/wonderswan.json"))
        unsupported_registration_keys = {
            "library",
            "library_id",
            "recent",
            "startup_action",
            "launcher",
        }
        self.assertTrue(
            unsupported_registration_keys.isdisjoint(
                set().union(*(all_keys(definition) for definition in definitions))
            )
        )

    def test_last_title_is_an_openfpga_data_slot_contract(self) -> None:
        definition = load_json(CORE_DIR / "data.json")
        slots = {int(slot["id"]): slot for slot in definition["data"]["data_slots"]}
        cartridge = slots[0]
        self.assertEqual(cartridge["extensions"], ["ws", "wsc"])
        parameters = int(cartridge["parameters"], 0)
        self.assertTrue(parameters & (1 << 9), "slot 0 must persist its browsed filename")
        self.assertTrue(parameters & (1 << 8), "slot 0 must request full core reload")

    def test_cartridge_bus_is_not_advertised(self) -> None:
        definition = load_json(CORE_DIR / "core.json")["core"]
        hardware = definition["framework"]["hardware"]
        self.assertEqual(hardware["cartridge_adapter"], -1)
        self.assertFalse(hardware["link_port"])

    def test_platform_image_is_openfpga_art_not_crc_library_art(self) -> None:
        platform_ids = load_json(CORE_DIR / "core.json")["core"]["metadata"][
            "platform_ids"
        ]
        self.assertEqual(platform_ids, ["wonderswan"])
        platform = load_json(DIST / "Platforms/wonderswan.json")["platform"]
        self.assertEqual(platform["name"], "WonderSwan")
        image = DIST / "Platforms/_images/wonderswan.bin"
        self.assertTrue(image.is_file())
        self.assertEqual(image.stat().st_size, 521 * 165 * 2)

    def test_documentation_keeps_the_supported_boundary_explicit(self) -> None:
        audit = AUDIT.read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        building = (ROOT / "BUILDING.md").read_text(encoding="utf-8")
        regression = (ROOT / "scripts/regression.sh").read_text(encoding="utf-8")
        for marker in (
            "Swan Song can be a polished, first-class **openFPGA** core",
            "does not provide a supported way",
            "/Platforms/_images/wonderswan.bin",
            "/System/Library/Images/<platform>/<crc32>.bin",
            "no public supported PocketOS plug-in",
            "will not ship such a patch",
        ):
            self.assertIn(marker, audit)
        self.assertIn("POCKET_LAUNCHER_LIBRARY.md", readme)
        self.assertIn("POCKET_LAUNCHER_LIBRARY.md", building)
        self.assertIn("pocket_launcher_library_contract_test.py", regression)


if __name__ == "__main__":
    unittest.main()
