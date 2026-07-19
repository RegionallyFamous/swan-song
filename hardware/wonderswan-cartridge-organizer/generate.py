#!/usr/bin/env python3
"""Generate print-ready WonderSwan cartridge organizer meshes.

Dependencies:
    python3 -m pip install trimesh shapely mapbox-earcut manifold3d matplotlib
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Polygon, box as rectangle
from shapely.ops import unary_union


@dataclass(frozen=True)
class OrganizerParameters:
    cartridge_width: float = 65.2
    cartridge_height: float = 41.8
    cartridge_thickness: float = 6.0
    slot_width: float = 6.8
    columns: int = 3
    rows: int = 3
    column_gap: float = 2.0
    side_margin: float = 4.0
    base_thickness: float = 3.0
    wall_thickness: float = 3.0
    floor_thickness: float = 3.0
    front_lip_height: float = 7.0
    back_support_height: float = 18.0
    row_pitch: float = 20.0
    row_rise: float = 13.0
    rear_margin: float = 5.0
    divider_thickness: float = 1.2
    divider_height: float = 6.0

    @property
    def width(self) -> float:
        return (
            self.columns * self.cartridge_width
            + (self.columns - 1) * self.column_gap
            + 2 * self.side_margin
        )

    @property
    def depth(self) -> float:
        return (
            (self.rows - 1) * self.row_pitch
            + self.wall_thickness
            + self.slot_width
            + self.wall_thickness
            + self.rear_margin
        )

    @property
    def height(self) -> float:
        last_floor = self.base_thickness + (self.rows - 1) * self.row_rise
        return last_floor + self.back_support_height


def extrude_cross_section(profile, width: float) -> trimesh.Trimesh:
    """Extrude a Y/Z profile along world X."""
    mesh = trimesh.creation.extrude_polygon(profile, height=width)
    local_to_world = np.array(
        [
            [0.0, 0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    mesh.apply_transform(local_to_world)
    return mesh


def bounded_box(
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    z0: float,
    z1: float,
) -> trimesh.Trimesh:
    extents = np.array([x1 - x0, y1 - y0, z1 - z0])
    center = np.array([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
    return trimesh.creation.box(
        extents=extents,
        transform=trimesh.transformations.translation_matrix(center),
    )


def organizer_profile(parameters: OrganizerParameters):
    p = parameters
    pieces = [rectangle(0, 0, p.depth, p.base_thickness)]

    for row in range(p.rows):
        front_y = row * p.row_pitch
        slot_front = front_y + p.wall_thickness
        back_y = slot_front + p.slot_width
        floor_z = p.base_thickness + row * p.row_rise

        if row > 0:
            shelf_bottom = floor_z - p.floor_thickness
            pieces.append(
                rectangle(front_y, shelf_bottom, back_y + p.wall_thickness, floor_z)
            )
            lower_support_z = max(p.base_thickness, shelf_bottom - p.row_rise + p.floor_thickness)
            pieces.append(
                Polygon(
                    [
                        (front_y, shelf_bottom),
                        (back_y, shelf_bottom),
                        (back_y, lower_support_z),
                    ]
                )
            )

        pieces.append(
            rectangle(
                front_y,
                floor_z,
                slot_front,
                floor_z + p.front_lip_height,
            )
        )
        pieces.append(
            rectangle(
                back_y,
                p.base_thickness,
                back_y + p.wall_thickness,
                floor_z + p.back_support_height,
            )
        )

    return unary_union(pieces).buffer(0)


def make_organizer(parameters: OrganizerParameters) -> trimesh.Trimesh:
    p = parameters
    rack = extrude_cross_section(organizer_profile(p), p.width)
    parts = [rack]

    for row in range(p.rows):
        front_y = row * p.row_pitch
        slot_front = front_y + p.wall_thickness
        slot_back = slot_front + p.slot_width
        floor_z = p.base_thickness + row * p.row_rise

        # Low ribs divide the continuous rail into cartridge-width bays.
        for column in range(1, p.columns):
            center_x = (
                p.side_margin
                + column * p.cartridge_width
                + (column - 0.5) * p.column_gap
            )
            parts.append(
                bounded_box(
                    center_x - p.divider_thickness / 2,
                    center_x + p.divider_thickness / 2,
                    slot_front - 0.2,
                    slot_back + 0.2,
                    floor_z,
                    floor_z + p.divider_height,
                )
            )

        # End stops prevent the outside cartridges from walking out sideways.
        for x0, x1 in ((0.0, 2.0), (p.width - 2.0, p.width)):
            parts.append(
                bounded_box(
                    x0,
                    x1,
                    slot_front - 0.2,
                    slot_back + 0.2,
                    floor_z,
                    floor_z + p.divider_height,
                )
            )

    result = trimesh.boolean.union(parts, engine="manifold", check_volume=False)
    result.remove_unreferenced_vertices()
    result.merge_vertices()
    result.fix_normals(multibody=False)
    return result


def make_clearance_coupon() -> tuple[trimesh.Trimesh, list[float]]:
    widths = [6.4, 6.8, 7.2]
    coupon_width = 35.0
    edge_margin = 2.0
    wall = 3.0
    base = 3.0
    wall_height = 10.0

    cursor = edge_margin
    parts = []
    wall_positions: list[tuple[float, float]] = []
    wall_positions.append((cursor, cursor + wall))
    cursor += wall
    for width in widths:
        cursor += width
        wall_positions.append((cursor, cursor + wall))
        cursor += wall
    coupon_depth = cursor + edge_margin

    parts.append(bounded_box(0, coupon_width, 0, coupon_depth, 0, base))
    for y0, y1 in wall_positions:
        parts.append(
            bounded_box(0, coupon_width, y0, y1, base, base + wall_height)
        )

    result = trimesh.boolean.union(parts, engine="manifold", check_volume=False)
    result.remove_unreferenced_vertices()
    result.merge_vertices()
    result.fix_normals(multibody=False)
    return result, widths


def validate_mesh(mesh: trimesh.Trimesh, expected_extents: np.ndarray, name: str) -> None:
    if not mesh.is_watertight:
        raise RuntimeError(f"{name} is not watertight")
    if not mesh.is_volume:
        raise RuntimeError(f"{name} does not enclose a valid volume")
    if not np.allclose(mesh.extents, expected_extents, atol=0.05):
        raise RuntimeError(
            f"{name} extents {mesh.extents} do not match expected {expected_extents}"
        )


def render_preview(
    mesh: trimesh.Trimesh,
    parameters: OrganizerParameters,
    output_path: Path,
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgba
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    p = parameters
    figure = plt.figure(figsize=(12, 8), dpi=160)
    axes = figure.add_subplot(111, projection="3d")

    triangles = [mesh.triangles]
    face_colors = [
        np.tile(to_rgba("#ded8cb"), (len(mesh.triangles), 1))
    ]

    cart_colors = ["#df4d5b", "#42a7a1", "#ecb646"]
    for row in range(p.rows):
        floor_z = p.base_thickness + row * p.row_rise
        slot_center_y = row * p.row_pitch + p.wall_thickness + p.slot_width / 2
        for column in range(p.columns):
            x0 = p.side_margin + column * (p.cartridge_width + p.column_gap)
            cart = bounded_box(
                x0,
                x0 + p.cartridge_width,
                slot_center_y - p.cartridge_thickness / 2,
                slot_center_y + p.cartridge_thickness / 2,
                floor_z,
                floor_z + p.cartridge_height,
            )
            triangles.append(cart.triangles)
            face_colors.append(
                np.tile(
                    to_rgba(cart_colors[row % len(cart_colors)]),
                    (len(cart.triangles), 1),
                )
            )

    combined_faces = Poly3DCollection(
        np.concatenate(triangles),
        facecolors=np.concatenate(face_colors),
        edgecolors="#343434",
        linewidths=0.16,
    )
    axes.add_collection3d(combined_faces)

    axes.set_xlim(0, p.width)
    axes.set_ylim(-8, p.depth)
    axes.set_zlim(0, p.base_thickness + (p.rows - 1) * p.row_rise + p.cartridge_height + 4)
    axes.set_box_aspect((p.width, p.depth * 1.2, 70))
    axes.view_init(elev=25, azim=-62)
    axes.set_axis_off()
    figure.patch.set_facecolor("white")
    axes.set_facecolor("white")
    figure.tight_layout(pad=0)
    figure.savefig(output_path, bbox_inches="tight", pad_inches=0.05)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent)
    parser.add_argument("--columns", type=int, default=3)
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--slot-width", type=float, default=6.8)
    parser.add_argument("--no-preview", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.columns < 1 or args.rows < 1:
        raise SystemExit("columns and rows must be positive")
    if args.slot_width <= 6.0:
        raise SystemExit("slot width should be greater than the nominal 6.0 mm cartridge")

    parameters = OrganizerParameters(
        columns=args.columns,
        rows=args.rows,
        slot_width=args.slot_width,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    organizer = make_organizer(parameters)
    organizer_name = f"wonderswan-organizer-{args.columns}x{args.rows}.stl"
    organizer_path = args.output_dir / organizer_name
    organizer.export(organizer_path)
    validate_mesh(
        organizer,
        np.array([parameters.width, parameters.depth, parameters.height]),
        "organizer",
    )

    coupon, coupon_widths = make_clearance_coupon()
    coupon_path = args.output_dir / "wonderswan-slot-clearance-test.stl"
    coupon.export(coupon_path)
    validate_mesh(coupon, coupon.extents, "clearance coupon")

    if not args.no_preview:
        render_preview(
            organizer,
            parameters,
            args.output_dir / "wonderswan-organizer-preview.png",
        )

    print(
        f"Wrote {organizer_path.name}: "
        f"{parameters.width:.1f} x {parameters.depth:.1f} x {parameters.height:.1f} mm, "
        f"watertight={organizer.is_watertight}, volume={organizer.volume / 1000:.1f} cm^3"
    )
    print(
        f"Wrote {coupon_path.name}: slots "
        + ", ".join(f"{width:.1f} mm" for width in coupon_widths)
    )


if __name__ == "__main__":
    main()
