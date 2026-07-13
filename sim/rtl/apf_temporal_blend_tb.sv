`timescale 1ns/1ps

module apf_temporal_blend_tb;
    reg [1:0] mode = 2'd0;
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
        .rgb_newest(rgb_newest),
        .rgb_previous(rgb_previous),
        .rgb_oldest(rgb_oldest),
        .rgb_out(rgb_out)
    );

    function automatic [7:0] expected_channel;
        input [1:0] expected_mode;
        input integer newest;
        input integer previous;
        input integer oldest;
        integer numerator;
        begin
            case (expected_mode)
                2'd1: begin
                    numerator = (newest + previous) * 17;
                    expected_channel = (numerator + 1) / 2;
                end
                2'd2: begin
                    numerator = (newest + previous + oldest) * 17;
                    expected_channel = (numerator + 1) / 3;
                end
                default: expected_channel = newest * 17;
            endcase
        end
    endfunction

    task automatic check_vector;
        reg [23:0] expected_rgb;
        begin
            #1ps;
            expected_rgb = {
                expected_channel(
                    mode,
                    rgb_newest[11:8],
                    rgb_previous[11:8],
                    rgb_oldest[11:8]
                ),
                expected_channel(
                    mode,
                    rgb_newest[7:4],
                    rgb_previous[7:4],
                    rgb_oldest[7:4]
                ),
                expected_channel(
                    mode,
                    rgb_newest[3:0],
                    rgb_previous[3:0],
                    rgb_oldest[3:0]
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

        // Every constant RGB444 value must remain its exact x17 RGB888 value
        // in all supported modes.
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

        // Exercise all 4,096 possible triples in all four encodings. Channel
        // permutations make every R/G/B output see the complete input space.
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

        $display("PASS APF temporal blend vectors=%0d", vector_count);
        $finish;
    end
endmodule
