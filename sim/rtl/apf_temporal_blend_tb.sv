`timescale 1ns/1ps

module apf_temporal_blend_tb;
    reg [1:0] mode = 2'd0;
    reg color_profile = 1'b0;
    reg [11:0] rgb_newest = 12'd0;
    reg [11:0] rgb_previous = 12'd0;
    reg [11:0] rgb_oldest = 12'd0;
    wire [23:0] rgb_out;

    integer mode_index;
    integer newest_index;
    integer previous_index;
    integer oldest_index;
    integer invariant_index;
    integer vector_count = 0;

    apf_temporal_blend dut (
        .mode(mode),
        .color_profile(color_profile),
        .rgb_newest(rgb_newest),
        .rgb_previous(rgb_previous),
        .rgb_oldest(rgb_oldest),
        .rgb_out(rgb_out)
    );

    function automatic [23:0] expected_color;
        input profile;
        input [11:0] sample;
        integer r;
        integer g;
        integer b;
        integer rr;
        integer gg;
        integer bb;
        begin
            r = sample[11:8];
            g = sample[7:4];
            b = sample[3:0];
            if (profile) begin
                rr = (r * 26 + g * 4 + b * 2) / 2;
                gg = (g * 24 + b * 8) / 2;
                bb = (r * 6 + g * 4 + b * 22) / 2;
            end else begin
                rr = r * 17;
                gg = g * 17;
                bb = b * 17;
            end
            expected_color = {rr[7:0], gg[7:0], bb[7:0]};
        end
    endfunction

    function automatic [7:0] expected_channel;
        input [1:0] expected_mode;
        input integer newest;
        input integer previous;
        input integer oldest;
        integer numerator;
        begin
            case (expected_mode)
                2'd1: begin
                    numerator = newest + previous;
                    expected_channel = (numerator + 1) / 2;
                end
                2'd2: begin
                    numerator = newest * 2 + previous + oldest;
                    expected_channel = numerator / 4;
                end
                default: expected_channel = newest;
            endcase
        end
    endfunction

    task automatic check_vector;
        reg [23:0] expected_rgb;
        reg [23:0] expected_newest;
        reg [23:0] expected_previous;
        reg [23:0] expected_oldest;
        begin
            #1ps;
            expected_newest = expected_color(color_profile, rgb_newest);
            expected_previous = expected_color(color_profile, rgb_previous);
            expected_oldest = expected_color(color_profile, rgb_oldest);
            expected_rgb = {
                expected_channel(
                    mode,
                    expected_newest[23:16],
                    expected_previous[23:16],
                    expected_oldest[23:16]
                ),
                expected_channel(
                    mode,
                    expected_newest[15:8],
                    expected_previous[15:8],
                    expected_oldest[15:8]
                ),
                expected_channel(
                    mode,
                    expected_newest[7:0],
                    expected_previous[7:0],
                    expected_oldest[7:0]
                )
            };
            if (rgb_out !== expected_rgb) begin
                $fatal(
                    1,
                    "blend mismatch mode=%0d newest=%03x previous=%03x oldest=%03x expected=%06x actual=%06x",
                    mode,
                    rgb_newest,
                    rgb_previous,
                    rgb_oldest,
                    expected_rgb,
                    rgb_out
                );
            end
            vector_count = vector_count + 1;
        end
    endtask

    initial begin
        color_profile = 1'b0;
        // Endpoint checks specifically reject the inherited paths that turned
        // two white frames into 247 and three white frames into about 242.
        mode = 2'd0;
        rgb_newest = 12'hFFF;
        rgb_previous = 12'h000;
        rgb_oldest = 12'h000;
        check_vector();
        if (rgb_out !== 24'hFFFFFF) $fatal(1, "Off did not preserve white");

        mode = 2'd1;
        rgb_previous = 12'hFFF;
        check_vector();
        if (rgb_out !== 24'hFFFFFF) $fatal(1, "two-frame white darkened");

        mode = 2'd2;
        rgb_oldest = 12'hFFF;
        check_vector();
        if (rgb_out !== 24'hFFFFFF) $fatal(1, "three-frame white darkened");

        // Every constant grayscale value must remain its exact x17 RGB888
        // value in every raw-profile mode.
        for (mode_index = 0; mode_index <= 2; mode_index = mode_index + 1) begin
            mode = mode_index[1:0];
            for (invariant_index = 0;
                 invariant_index < 16;
                 invariant_index = invariant_index + 1) begin
                rgb_newest = {3{invariant_index[3:0]}};
                rgb_previous = rgb_newest;
                rgb_oldest = rgb_newest;
                check_vector();
                if (rgb_out !== {3{invariant_index[3:0], invariant_index[3:0]}}) begin
                    $fatal(
                        1,
                        "equal-input invariant failed mode=%0d value=%0d output=%06x",
                        mode_index,
                        invariant_index,
                        rgb_out
                    );
                end
            end
        end

        // Exercise all 4,096 possible per-channel triples in all four temporal
        // encodings. Channel permutations make every R/G/B output see the
        // complete raw-profile input space.
        for (mode_index = 0; mode_index < 4; mode_index = mode_index + 1) begin
            mode = mode_index[1:0];
            for (newest_index = 0;
                 newest_index < 16;
                 newest_index = newest_index + 1) begin
                for (previous_index = 0;
                     previous_index < 16;
                     previous_index = previous_index + 1) begin
                    for (oldest_index = 0;
                         oldest_index < 16;
                         oldest_index = oldest_index + 1) begin
                        rgb_newest = {
                            newest_index[3:0],
                            previous_index[3:0],
                            oldest_index[3:0]
                        };
                        rgb_previous = {
                            previous_index[3:0],
                            oldest_index[3:0],
                            newest_index[3:0]
                        };
                        rgb_oldest = {
                            oldest_index[3:0],
                            newest_index[3:0],
                            previous_index[3:0]
                        };
                        check_vector();

                        // Reserved mode must fail closed to newest-only; it
                        // may not accidentally enable an undocumented blend.
                        if (mode_index == 3 &&
                            rgb_out !== {
                                rgb_newest[11:8], rgb_newest[11:8],
                                rgb_newest[7:4], rgb_newest[7:4],
                                rgb_newest[3:0], rgb_newest[3:0]
                            }) begin
                            $fatal(1, "reserved mode did not clamp to Off");
                        end
                    end
                end
            end
        end

        // The optional color profile must match the pinned ares matrix for
        // every one of the 4,096 native RGB444 colors. These primaries and
        // white also make channel ordering and the 240 white ceiling explicit.
        color_profile = 1'b1;
        mode = 2'd0;
        for (newest_index = 0; newest_index < 4096;
             newest_index = newest_index + 1) begin
            rgb_newest = newest_index[11:0];
            rgb_previous = 12'hA55;
            rgb_oldest = 12'h5AA;
            check_vector();
        end
        rgb_newest = 12'hF00;
        check_vector();
        if (rgb_out !== 24'hC3002D) $fatal(1, "ares red primary mismatch");
        rgb_newest = 12'h0F0;
        check_vector();
        if (rgb_out !== 24'h1EB41E) $fatal(1, "ares green primary mismatch");
        rgb_newest = 12'h00F;
        check_vector();
        if (rgb_out !== 24'h0F3CA5) $fatal(1, "ares blue primary mismatch");
        rgb_newest = 12'hFFF;
        check_vector();
        if (rgb_out !== 24'hF0F0F0) $fatal(1, "ares white mismatch");

        // Exhaust every source color through every temporal encoding with
        // adversarial, cross-channel prior samples. This covers the complete
        // profile lookup domain and both arithmetic formulas without claiming
        // the impossible 4096^3 Cartesian product is required for three
        // independent 12-bit samples.
        for (mode_index = 0; mode_index < 4; mode_index = mode_index + 1) begin
            mode = mode_index[1:0];
            for (newest_index = 0; newest_index < 4096;
                 newest_index = newest_index + 1) begin
                rgb_newest = newest_index[11:0];
                rgb_previous = {
                    ~newest_index[3:0],
                    newest_index[11:8],
                    newest_index[7:4]
                };
                rgb_oldest = {
                    newest_index[7:4],
                    ~newest_index[3:0],
                    newest_index[11:8]
                };
                check_vector();
            end
        end

        // The finite response is exact for its documented 50/25/25 formula:
        // a black history followed by white yields floor(255/2), while a
        // constant white history remains the profile's 240-level white.
        mode = 2'd2;
        rgb_newest = 12'hFFF;
        rgb_previous = 12'h000;
        rgb_oldest = 12'h000;
        check_vector();
        if (rgb_out !== 24'h787878) $fatal(1, "LCD response first step mismatch");
        rgb_previous = 12'hFFF;
        rgb_oldest = 12'hFFF;
        check_vector();
        if (rgb_out !== 24'hF0F0F0) $fatal(1, "LCD response constant mismatch");

        $display(
            "PASS APF temporal blend vectors=%0d raw=4096-triples ares=4096-colors",
            vector_count
        );
        $finish;
    end
endmodule
