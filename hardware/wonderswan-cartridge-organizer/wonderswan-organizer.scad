// Parametric WonderSwan cartridge organizer and fit coupon.
// Open in OpenSCAD, set `part`, press F6, then export STL.

part = "organizer"; // "organizer" or "coupon"

cartridge_width = 65.2;
cartridge_height = 41.8;
cartridge_thickness = 6.0;
slot_width = 6.8;

columns = 3;
rows = 3;
column_gap = 2.0;
side_margin = 4.0;

base_thickness = 3.0;
wall_thickness = 3.0;
floor_thickness = 3.0;
front_lip_height = 7.0;
back_support_height = 18.0;
row_pitch = 20.0;
row_rise = 13.0;
rear_margin = 5.0;
divider_thickness = 1.2;
divider_height = 6.0;

organizer_width = columns * cartridge_width
    + (columns - 1) * column_gap
    + 2 * side_margin;
organizer_depth = (rows - 1) * row_pitch
    + wall_thickness + slot_width + wall_thickness + rear_margin;

module profile_extrusion(width) {
    multmatrix([
        [0, 0, 1, 0],
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1]
    ])
        linear_extrude(height = width)
            children();
}

module organizer_profile() {
    union() {
        square([organizer_depth, base_thickness]);

        for (row = [0 : rows - 1]) {
            front_y = row * row_pitch;
            slot_front = front_y + wall_thickness;
            back_y = slot_front + slot_width;
            floor_z = base_thickness + row * row_rise;

            if (row > 0) {
                shelf_bottom = floor_z - floor_thickness;
                lower_support_z = max(
                    base_thickness,
                    shelf_bottom - row_rise + floor_thickness
                );
                translate([front_y, shelf_bottom])
                    square([
                        back_y + wall_thickness - front_y,
                        floor_thickness
                    ]);
                polygon([
                    [front_y, shelf_bottom],
                    [back_y, shelf_bottom],
                    [back_y, lower_support_z]
                ]);
            }

            translate([front_y, floor_z])
                square([wall_thickness, front_lip_height]);
            translate([back_y, base_thickness])
                square([
                    wall_thickness,
                    floor_z + back_support_height - base_thickness
                ]);
        }
    }
}

module organizer() {
    union() {
        profile_extrusion(organizer_width)
            organizer_profile();

        for (row = [0 : rows - 1]) {
            slot_front = row * row_pitch + wall_thickness;
            floor_z = base_thickness + row * row_rise;

            for (column = [1 : columns - 1]) {
                center_x = side_margin
                    + column * cartridge_width
                    + (column - 0.5) * column_gap;
                translate([
                    center_x - divider_thickness / 2,
                    slot_front - 0.2,
                    floor_z
                ])
                    cube([
                        divider_thickness,
                        slot_width + 0.4,
                        divider_height
                    ]);
            }

            for (x0 = [0, organizer_width - 2]) {
                translate([x0, slot_front - 0.2, floor_z])
                    cube([2, slot_width + 0.4, divider_height]);
            }
        }
    }
}

module clearance_coupon() {
    test_slots = [6.4, 6.8, 7.2];
    coupon_width = 35;
    edge_margin = 2;
    coupon_wall = 3;
    coupon_base = 3;
    coupon_wall_height = 10;
    coupon_depth = 2 * edge_margin
        + (len(test_slots) + 1) * coupon_wall
        + test_slots[0] + test_slots[1] + test_slots[2];

    union() {
        cube([coupon_width, coupon_depth, coupon_base]);
        translate([0, edge_margin, coupon_base])
            cube([coupon_width, coupon_wall, coupon_wall_height]);

        translate([
            0,
            edge_margin + coupon_wall + test_slots[0],
            coupon_base
        ])
            cube([coupon_width, coupon_wall, coupon_wall_height]);

        translate([
            0,
            edge_margin + 2 * coupon_wall + test_slots[0] + test_slots[1],
            coupon_base
        ])
            cube([coupon_width, coupon_wall, coupon_wall_height]);

        translate([
            0,
            edge_margin + 3 * coupon_wall
                + test_slots[0] + test_slots[1] + test_slots[2],
            coupon_base
        ])
            cube([coupon_width, coupon_wall, coupon_wall_height]);
    }
}

if (part == "organizer") {
    organizer();
} else {
    clearance_coupon();
}
